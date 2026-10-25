"""
Qdrant Vector Database Integration & Embedding Manager

Manages the lifecycle of vector collections, payload indices, dense embedding models,
and similarity search queries within Qdrant Cloud for SmallBook:
    - Collection: `smallbook_child_chunks` (768-dimensional Cosine distance vectors).
    - Payload Index: Keyword index on `source_id` enabling fast tenant/source-scoped filtering.
    - Embedding Model: Cached `SentenceTransformer(ACTIVE_MODEL)` loaded locally or from HuggingFace.
"""

import os
import time
import logging
from qdrant_client import QdrantClient
from qdrant_client.http.models import Distance, VectorParams, PointStruct
from sentence_transformers import SentenceTransformer
from app.models.ingestion_models import ChildChunk
from app.services.ingestion.config import ACTIVE_MODEL, DEFAULT_BATCH_SIZE

logger = logging.getLogger(__name__)

# Global embedding model cache to eliminate repeated weights loading
_embedding_model = None


def get_embedding_model() -> SentenceTransformer:
    """
    Retrieves the global cached SentenceTransformer embedding model singleton.

    Attempts local cached loading first; falls back to HuggingFace Hub download if needed.

    Returns:
        SentenceTransformer: Initialized sentence transformer model instance.
    """
    global _embedding_model
    if _embedding_model is None:
        try:
            _embedding_model = SentenceTransformer(ACTIVE_MODEL, local_files_only=True)
        except Exception:
            _embedding_model = SentenceTransformer(ACTIVE_MODEL)
    return _embedding_model


# Global client and collection initialization verification flags
_qdrant_client = None
_collection_verified = False


class QdrantManager:
    """
    Qdrant Cloud Client & Vector Collection Controller.

    Handles point upserts, vector similarity searches, payload filtering,
    and bulk point deletions by source ID.
    """
    def __init__(self):
        """Initializes the QdrantClient connection and verifies target collection existence."""
        global _qdrant_client
        if _qdrant_client is None:
            timeout_sec = float(os.environ.get("QDRANT_TIMEOUT", "60.0"))
            _qdrant_client = QdrantClient(
                url=os.environ.get("QDRANT_URL"),
                api_key=os.environ.get("QDRANT_API_KEY"),
                timeout=timeout_sec,
            )
        self.client = _qdrant_client
        self.collection_name = "smallbook_child_chunks"
        # BAAI/bge-base-en-v1.5 has 768 dimensions
        self.vector_size = 768  
        self._ensure_collection_exists()

    def _ensure_collection_exists(self):
        """
        Idempotently verifies and creates the Qdrant collection and payload indexes.

        Ensures the collection exists with 768 dimensions and Cosine distance metric.
        Creates a keyword payload index on `source_id` for fast filtered queries.
        Uses a process-level cache flag (`_collection_verified`) to eliminate redundant HTTP calls.
        """
        global _collection_verified
        if _collection_verified:
            return

        try:
            if not self.client.collection_exists(self.collection_name):
                self.client.create_collection(
                    collection_name=self.collection_name,
                    vectors_config=VectorParams(size=self.vector_size, distance=Distance.COSINE),
                )
                from qdrant_client.http.models import PayloadSchemaType
                try:
                    self.client.create_payload_index(
                        collection_name=self.collection_name,
                        field_name="source_id",
                        field_schema=PayloadSchemaType.KEYWORD
                    )
                except Exception as e:
                    print(f"Failed to create Qdrant payload index: {e}")
            _collection_verified = True
        except Exception as e:
            print(f"Failed to verify/create Qdrant collection: {e}")

    def embed_and_upsert(self, children: list[ChildChunk]):
        """
        Embeds child chunk text strings and uploads vectorized points into Qdrant.

        1. Generates 768-d normalized embeddings using `SentenceTransformer`.
        2. Constructs `PointStruct` records containing child chunk text, `parent_id`, and `source_id`.
        3. Upserts points to Qdrant in batches of 250 with `wait=False` for fast async indexing.

        Args:
            children: List of ChildChunk instances to embed and store.
        """
        if not children:
            return

        texts = [c.text for c in children]
        
        # 1. Generate normalized embeddings in batches
        model = get_embedding_model()
        embeddings = model.encode(
            texts, 
            batch_size=DEFAULT_BATCH_SIZE, 
            normalize_embeddings=True, 
            show_progress_bar=False
        )

        # 2. Prepare Qdrant PointStruct payloads
        points = []
        for idx, child in enumerate(children):
            points.append(
                PointStruct(
                    id=child.id,  # Must be a valid UUID string
                    vector=embeddings[idx].tolist(),
                    payload={
                        "parent_id": child.parent_id,
                        "source_id": child.source_id,
                        "text": child.text,  # Stored in payload for CrossEncoder reranking
                        "order": child.order
                    }
                )
            )

        # 3. Upsert to Qdrant Cloud in smaller batches with retries to prevent timeouts on slow internet
        batch_size = int(os.environ.get("QDRANT_BATCH_SIZE", "50"))
        max_retries = 3

        for i in range(0, len(points), batch_size):
            batch = points[i:i + batch_size]
            last_err = None
            for attempt in range(1, max_retries + 1):
                try:
                    self.client.upsert(
                        collection_name=self.collection_name,
                        points=batch,
                        wait=False
                    )
                    last_err = None
                    break
                except Exception as exc:
                    last_err = exc
                    logger.warning(
                        f"Qdrant upsert attempt {attempt}/{max_retries} failed for batch {i // batch_size + 1}: {exc}"
                    )
                    if attempt < max_retries:
                        time.sleep(1.5 * attempt)
            if last_err is not None:
                logger.error(f"Failed to upsert batch {i // batch_size + 1} to Qdrant after {max_retries} attempts.")
                raise last_err

    def delete_by_source_id(self, source_id: str):
        """
        Deletes all vector points associated with a specific source document ID.

        Args:
            source_id: UUID string of the deleted source document.
        """
        from qdrant_client.http.models import Filter, FieldCondition, MatchValue
        self.client.delete(
            collection_name=self.collection_name,
            points_selector=Filter(
                must=[
                    FieldCondition(
                        key="source_id",
                        match=MatchValue(value=source_id)
                    )
                ]
            ),
            wait=False
        )

    def search_child_chunks(
        self, 
        query_vector: list[float], 
        source_ids: list[str] | None = None, 
        limit: int = 20
    ) -> list[dict]:
        """
        Queries Qdrant Cloud for the nearest child chunk vectors.

        Supports optional filtering by a list of allowed source document UUIDs.

        Args:
            query_vector: 768-dimensional normalized query embedding vector.
            source_ids: Optional list of source UUID strings to filter against.
            limit: Maximum number of closest matches to return.

        Returns:
            list[dict]: Matched points with score, parent_id, source_id, text, and order.
        """
        from qdrant_client.http.models import Filter, FieldCondition, MatchAny, MatchValue

        query_filter = None
        if source_ids:
            if len(source_ids) == 1:
                query_filter = Filter(
                    must=[FieldCondition(key="source_id", match=MatchValue(value=source_ids[0]))]
                )
            else:
                query_filter = Filter(
                    must=[FieldCondition(key="source_id", match=MatchAny(any=source_ids))]
                )

        response = self.client.query_points(
            collection_name=self.collection_name,
            query=query_vector,
            query_filter=query_filter,
            limit=limit,
            with_payload=True
        )

        results = []
        for point in response.points:
            payload = point.payload or {}
            results.append({
                "id": str(point.id),
                "score": float(point.score),
                "parent_id": payload.get("parent_id"),
                "source_id": payload.get("source_id"),
                "text": payload.get("text", ""),
                "order": payload.get("order", 0)
            })
        return results