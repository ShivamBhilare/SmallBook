import os
import numpy as np
from qdrant_client import QdrantClient
from qdrant_client.http.models import Distance, VectorParams, PointStruct
from sentence_transformers import SentenceTransformer
from app.models.ingestion_models import ChildChunk
from app.services.ingestion.config import ACTIVE_MODEL, DEFAULT_BATCH_SIZE

# Global Model Cache
_embedding_model = None

def get_embedding_model():
    global _embedding_model
    if _embedding_model is None:
        try:
            _embedding_model = SentenceTransformer(ACTIVE_MODEL, local_files_only=True)
        except Exception:
            _embedding_model = SentenceTransformer(ACTIVE_MODEL)
    return _embedding_model

# Global Client Cache
_qdrant_client = None
_collection_verified = False

class QdrantManager:
    def __init__(self):
        global _qdrant_client
        if _qdrant_client is None:
            _qdrant_client = QdrantClient(
                url=os.environ.get("QDRANT_URL"),
                api_key=os.environ.get("QDRANT_API_KEY"),
            )
        self.client = _qdrant_client
        self.collection_name = "smallbook_child_chunks"
        # BAAI/bge-base-en-v1.5 has 768 dimensions
        self.vector_size = 768  
        self._ensure_collection_exists()

    def _ensure_collection_exists(self):
        """Creates the Qdrant collection if it doesn't exist (cached)."""
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
        """Embeds text and uploads vectors to Qdrant with payload metadata."""
        if not children:
            return

        texts = [c.text for c in children]
        
        # 1. Generate Embeddings
        model = get_embedding_model()
        embeddings = model.encode(
            texts, 
            batch_size=DEFAULT_BATCH_SIZE, 
            normalize_embeddings=True, 
            show_progress_bar=False
        )

        # 2. Prepare Qdrant Points
        points = []
        for idx, child in enumerate(children):
            points.append(
                PointStruct(
                    id=child.id,  # Must be a valid UUID string
                    vector=embeddings[idx].tolist(),
                    payload={
                        "parent_id": child.parent_id,
                        "source_id": child.source_id,
                        "text": child.text,  # Optional: Store text for CrossEncoder reranking later
                        "order": child.order
                    }
                )
            )

        # 3. Upsert to Qdrant Cloud in batches (Wait=False for asynchronous background speed)
        batch_size = 250
        for i in range(0, len(points), batch_size):
            batch = points[i:i + batch_size]
            self.client.upsert(
                collection_name=self.collection_name,
                points=batch,
                wait=False
            )

    def delete_by_source_id(self, source_id: str):
        """Deletes all vector points associated with a specific source_id."""
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