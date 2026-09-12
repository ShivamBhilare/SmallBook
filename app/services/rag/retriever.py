"""
Hybrid Document Retriever & Context Assembly Pipeline

Implements SmallBook's two-stage hierarchical retrieval architecture:
    1. Vector Semantic Search: Dense retrieval over child chunk embeddings in Qdrant.
    2. Precision Reranking: Sentence-Transformers Cross-Encoder (`ms-marco-MiniLM-L-6-v2`)
       with domain entity boosting for figures, equations, and tables.
    3. Parent Resolution: Maps winning child scores to macro parent chunks in PostgreSQL.
    4. Context Expansion: Fetches adjacent neighboring parent chunks for narrative continuity.
    5. Token Budgeting: Assembles chunks within the prompt token budget via `tiktoken`.
    6. Multi-Query Decomposition: Splits complex compound queries ('and') into sub-queries.
"""

import re
import time
from typing import Optional, Dict
import tiktoken
from supabase import Client
from sentence_transformers import CrossEncoder

from app.models.ingestion_models import ParentChunk
from app.services.ingestion.config import (
    TOP_K_HYBRID,
    TOP_N_PARENTS,
    NEIGHBOR_WINDOW,
    CONTEXT_TOKEN_BUDGET,
    QUESTION_STARTERS,
    CROSS_ENCODER_MODEL
)
from app.services.ingestion.qdrant_db import get_embedding_model, QdrantManager
from app.services.authentication.auth_service import get_service_role_client

# Global model and tokenizer singletons to avoid repeated instantiation overhead
_cross_encoder_model = None
_tokenizer = None


def get_cross_encoder_model() -> CrossEncoder:
    """
    Loads and caches the local CrossEncoder reranking model singleton.

    Attempts local weights loading first; falls back to HuggingFace download if uninitialized.

    Returns:
        CrossEncoder: Initialized CrossEncoder model instance.
    """
    global _cross_encoder_model
    if _cross_encoder_model is None:
        try:
            _cross_encoder_model = CrossEncoder(CROSS_ENCODER_MODEL, local_files_only=True)
        except Exception:
            _cross_encoder_model = CrossEncoder(CROSS_ENCODER_MODEL)
    return _cross_encoder_model


def get_tokenizer():
    """
    Caches and returns the `tiktoken` BPE tokenizer (`cl100k_base`).

    Returns:
        Encoding: Cached tiktoken encoding instance.
    """
    global _tokenizer
    if _tokenizer is None:
        _tokenizer = tiktoken.get_encoding("cl100k_base")
    return _tokenizer


def _token_count(text: str, tokenizer=None) -> int:
    """
    Computes the token count of a given text string using tiktoken.

    Args:
        text: Input string.
        tokenizer: Optional pre-resolved tokenizer instance.

    Returns:
        int: Number of BPE tokens in the text.
    """
    tok = tokenizer or get_tokenizer()
    return len(tok.encode(text))


# =========================================================================
# 1. QUERY DECOMPOSITION & NEIGHBOR HELPERS
# =========================================================================

def decompose_query(query: str) -> list[str]:
    """
    Splits compound user queries containing 'and' into discrete sub-queries.

    Only splits when subsequent clauses begin with recognized question starters
    (e.g., 'What is X and how does Y work?').

    Args:
        query: Raw user query string.

    Returns:
        list[str]: List of decomposed sub-queries, or original query if not compound.
    """
    parts = re.split(r"\s+and\s+", query, flags=re.IGNORECASE)
    if len(parts) == 1:
        return [query]

    sub_queries: list[str] = []
    buffer = ""
    for part in parts:
        first_word = part.strip().rstrip("?").split(" ", 1)[0].lower() if part.strip() else ""
        if first_word in QUESTION_STARTERS and buffer:
            sub_queries.append(buffer.strip())
            buffer = part
        else:
            buffer = f"{buffer} and {part}" if buffer else part
    if buffer:
        sub_queries.append(buffer.strip())

    return sub_queries if len(sub_queries) > 1 else [query]


def _get_neighboring_parents(
    all_parents: list[ParentChunk], 
    best_parent: ParentChunk, 
    window: int
) -> list[ParentChunk]:
    """
    Retrieves adjacent parent chunks within the same document for context continuity.

    Args:
        all_parents: Candidate pool of parent chunks.
        best_parent: The highest scoring parent chunk.
        window: Number of neighboring offsets (+/-) to include.

    Returns:
        list[ParentChunk]: Adjacent parent chunks from the same document.
    """
    same_doc = {p.order: p for p in all_parents if p.document_id == best_parent.document_id}
    neighbors = []
    for offset in range(1, window + 1):
        for order in (best_parent.order - offset, best_parent.order + offset):
            if order in same_doc:
                neighbors.append(same_doc[order])
    return neighbors


# =========================================================================
# 2. CORE RETRIEVAL PIPELINE
# =========================================================================

def retrieve(
    query: str,
    source_ids: Optional[list[str]] = None,
    client: Optional[Client] = None,
    parents_cache: Optional[list[ParentChunk]] = None,
    top_k: Optional[int] = None,
    top_n_parents: Optional[int] = None,
    neighbor_window: Optional[int] = None,
    context_token_budget: Optional[int] = None,
    min_rerank_score: float = -2.0,
) -> Optional[dict]:
    """
    Executes the complete two-stage hierarchical retrieval algorithm:
    1. Dense Vector Search: Queries Qdrant Cloud for candidate child chunks scoped to `source_ids`.
    2. Cross-Encoder Reranking: Predicts pairwise relevance scores with heuristic entity boosts.
    3. Score Aggregation: Maps maximum child scores to their respective parent chunk IDs.
    4. Database Hydration: Retrieves winning parent chunks and adjacent neighbor chunks from Supabase.
    5. Token Budget Allocation: Selects chunks up to `context_token_budget` without exceeding limits.

    Args:
        query: User search or chat prompt query.
        source_ids: Optional list of source document UUIDs to scope vector search.
        client: Optional Supabase client instance.
        parents_cache: Optional pre-loaded parent chunks to bypass database queries.
        top_k: Top candidate children to retrieve from Qdrant (defaults to TOP_K_HYBRID).
        top_n_parents: Number of top winning parent chunks to select (defaults to TOP_N_PARENTS).
        neighbor_window: Adjacent chunk offset distance for context expansion.
        context_token_budget: Maximum allowed tokens for assembled prompt context.
        min_rerank_score: Minimum CrossEncoder score required for a chunk to be considered relevant.

    Returns:
        Optional[dict]: Structured retrieval payload with selected parents and timings, or None.
    """
    top_k = TOP_K_HYBRID if top_k is None else top_k
    top_n_parents = TOP_N_PARENTS if top_n_parents is None else top_n_parents
    neighbor_window = NEIGHBOR_WINDOW if neighbor_window is None else neighbor_window
    context_token_budget = CONTEXT_TOKEN_BUDGET if context_token_budget is None else context_token_budget

    timings = {}
    
    # 1. Dense Semantic Vector Search in Qdrant Cloud
    t0 = time.perf_counter()
    embedder = get_embedding_model()
    query_vector = embedder.encode(query, normalize_embeddings=True).tolist()
    
    qdrant = QdrantManager()
    candidate_children = qdrant.search_child_chunks(
        query_vector=query_vector,
        source_ids=source_ids,
        limit=top_k
    )
    timings["qdrant_search_ms"] = (time.perf_counter() - t0) * 1000

    if not candidate_children:
        return None

    # 2. Cross-Encoder Reranking on Child Chunks
    t0 = time.perf_counter()
    reranker = get_cross_encoder_model()
    pairs = [[query, child["text"]] for child in candidate_children]
    rerank_scores = reranker.predict(pairs)
    timings["cross_encoder_ms"] = (time.perf_counter() - t0) * 1000

    # Extract Key Identifiers (e.g., "Figure 1-21", "Table 3") for entity boosting
    entity_matches = re.findall(r"(figure\s+\d+[\-\d]*|table\s+\d+)", query, flags=re.IGNORECASE)

    # 3. Aggregate Child scores to Parent IDs
    parent_scores: Dict[str, float] = {}
    for child, score in zip(candidate_children, rerank_scores):
        pid = child.get("parent_id")
        if not pid:
            continue
            
        score_val = float(score)
        # Apply entity boost if explicit figures or tables match
        if entity_matches:
            for em in entity_matches:
                if em.lower() in child["text"].lower():
                    score_val += 3.0
        
        if pid not in parent_scores or score_val > parent_scores[pid]:
            parent_scores[pid] = score_val

    # Filter out scores below relevance threshold and sort
    valid_parent_ids = [
        pid for pid, score in parent_scores.items() 
        if score >= min_rerank_score
    ]
    valid_parent_ids.sort(key=lambda pid: parent_scores[pid], reverse=True)

    if not valid_parent_ids:
        return None

    selected_parent_ids = valid_parent_ids[:top_n_parents]

    # 4. Fetch Winning Parent Chunks and Neighbor Chunks from Supabase (or cache)
    supabase_client = client or get_service_role_client()
    
    primary_parents: list[ParentChunk] = []
    all_known_parents: dict[str, ParentChunk] = {}

    if parents_cache:
        all_known_parents = {p.id: p for p in parents_cache}
    else:
        # Query Supabase document_chunks for the winning parent IDs
        try:
            res = supabase_client.table("document_chunks").select("*").in_("id", valid_parent_ids).execute()
            for row in (res.data or []):
                chunk = ParentChunk(
                    id=row["id"],
                    notebook_id="current",
                    document_id=row["source_id"],
                    text=row["chunk_text"],
                    order=row.get("chunk_index", 0),
                    score=float(parent_scores.get(row["id"], 1.0))
                )
                all_known_parents[chunk.id] = chunk
        except Exception as e:
            print(f"Error fetching parent chunks from Supabase: {e}")

    for pid in selected_parent_ids:
        if pid in all_known_parents:
            p_chunk = all_known_parents[pid]
            if pid in parent_scores:
                p_chunk.score = float(parent_scores[pid])
            primary_parents.append(p_chunk)

    if not primary_parents:
        return None

    # 5. Extract Neighboring Chunks for Context Continuity
    best_parent = primary_parents[0]
    neighbor_parents: list[ParentChunk] = []

    # If not present in cache, try fetching adjacent indices from Supabase
    if not parents_cache:
        target_orders = [best_parent.order - 1, best_parent.order + 1]
        try:
            n_res = supabase_client.table("document_chunks")\
                .select("*")\
                .eq("source_id", best_parent.document_id)\
                .in_("chunk_index", target_orders)\
                .execute()
            for row in (n_res.data or []):
                n_chunk = ParentChunk(
                    id=row["id"],
                    notebook_id="current",
                    document_id=row["source_id"],
                    text=row["chunk_text"],
                    order=row.get("chunk_index", 0),
                    score=float(parent_scores.get(row["id"], 0.8))
                )
                if n_chunk.id not in [p.id for p in primary_parents]:
                    neighbor_parents.append(n_chunk)
        except Exception as e:
            print(f"Error fetching neighbor chunks: {e}")
    else:
        neighbor_parents = [
            p for p in _get_neighboring_parents(list(all_known_parents.values()), best_parent, neighbor_window)
            if p not in primary_parents
        ]

    # 6. Context Token Budgeting
    tokenizer = get_tokenizer()
    selected_parents: list[ParentChunk] = []
    used_tokens = 0

    for parent in primary_parents + neighbor_parents:
        cost = _token_count(parent.text, tokenizer)
        if used_tokens + cost > context_token_budget and selected_parents:
            break
        selected_parents.append(parent)
        used_tokens += cost

    return {
        "query": query,
        "candidate_children": candidate_children,
        "primary_parents": primary_parents,
        "neighbor_parents": neighbor_parents,
        "selected_parents": selected_parents,
        "used_tokens": used_tokens,
        "timings_ms": timings,
    }


# =========================================================================
# 3. MULTI-QUERY RETRIEVAL
# =========================================================================

def retrieve_multi(
    query: str,
    source_ids: Optional[list[str]] = None,
    client: Optional[Client] = None,
    **kwargs
) -> Optional[dict]:
    """
    Handles complex multi-part queries by decomposing them into sub-queries.

    Executes targeted retrieval for each sub-query, aggregates and deduplicates
    parent chunks, and allocates context tokens evenly across query aspects.

    Args:
        query: Compound user query.
        source_ids: Optional list of source UUID strings.
        client: Optional Supabase client instance.
        **kwargs: Additional overrides passed to `retrieve`.

    Returns:
        Optional[dict]: Merged multi-query retrieval result dictionary.
    """
    sub_queries = decompose_query(query)
    if len(sub_queries) == 1:
        return retrieve(query, source_ids=source_ids, client=client, **kwargs)

    context_token_budget = kwargs.pop("context_token_budget", CONTEXT_TOKEN_BUDGET)
    per_sub_budget = max(1000, context_token_budget // len(sub_queries))

    seen_ids = set()
    merged_primary: list[ParentChunk] = []
    merged_neighbor: list[ParentChunk] = []
    all_timings = {}

    for sq in sub_queries:
        r = retrieve(sq, source_ids=source_ids, client=client, context_token_budget=per_sub_budget, **kwargs)
        if r is None:
            continue
        all_timings[sq] = r.get("timings_ms", {})
        for p in r.get("primary_parents", []):
            if p.id not in seen_ids:
                seen_ids.add(p.id)
                merged_primary.append(p)
        for p in r.get("neighbor_parents", []):
            if p.id not in seen_ids:
                seen_ids.add(p.id)
                merged_neighbor.append(p)

    if not merged_primary and not merged_neighbor:
        return None

    # Final token budget assembly across all sub-query parents
    tokenizer = get_tokenizer()
    selected: list[ParentChunk] = []
    used_tokens = 0
    for parent in merged_primary + merged_neighbor:
        cost = _token_count(parent.text, tokenizer)
        if used_tokens + cost > context_token_budget and selected:
            break
        selected.append(parent)
        used_tokens += cost

    return {
        "sub_queries": sub_queries,
        "primary_parents": merged_primary,
        "neighbor_parents": merged_neighbor,
        "selected_parents": selected,
        "used_tokens": used_tokens,
        "timings_ms": all_timings,
    }