"""
Ingestion & Retrieval Pipeline Configuration Hyperparameters

Centralizes model identifiers, chunk token boundaries, overlap windows,
and reranking thresholds used throughout the RAG ingestion and retrieval pipelines.
"""

# =========================================================================
# 1. EMBEDDING MODEL & BATCH INFERENCE
# =========================================================================

# HuggingFace sentence-transformer model identifier for dense child chunk embeddings (768 dimensions)
ACTIVE_MODEL = "BAAI/bge-base-en-v1.5"

# Batch size for vectorized embedding generation in worker processes
DEFAULT_BATCH_SIZE = 64


# =========================================================================
# 2. HIERARCHICAL PARENT-CHILD CHUNKING LIMITS
# =========================================================================

# Macro parent chunk token boundary providing extensive surrounding narrative context for synthesis
PARENT_CHUNK_TOKENS = 1000

# Overlap tokens between adjacent parent chunks to avoid semantic boundary clipping
PARENT_OVERLAP_TOKENS = 50

# Micro child chunk token boundary optimized for granular sentence-level semantic vector matching
CHILD_CHUNK_TOKENS = 150

# Overlap tokens between adjacent child chunks within the same parent
CHILD_OVERLAP_TOKENS = 25


# =========================================================================
# 3. CONTEXT BUDGET & HEURISTICS
# =========================================================================

# Number of adjacent parent chunks to include around a retrieved hit for surrounding context expansion
NEIGHBOR_WINDOW = 1

# Maximum cumulative tokens reserved in the LLM prompt for grounded source context snippets
CONTEXT_TOKEN_BUDGET = 5000

# Canonical interrogative words used to distinguish analytical queries from casual conversational statements
QUESTION_STARTERS = ("what", "why", "how", "when", "where", "who", "which", "is", "are", "does", "do", "can", "list")


# =========================================================================
# 4. CROSS-ENCODER RERANKING & RETRIEVAL HYBRID TUNING
# =========================================================================

# Cross-encoder model used for second-stage precision reranking of vector search results
CROSS_ENCODER_MODEL = "cross-encoder/ms-marco-MiniLM-L-6-v2"

# Initial top-K child chunks retrieved from Qdrant vector similarity search before reranking
TOP_K_HYBRID = 20

# Top-N parent document chunks selected after cross-encoder reranking to inject into LLM synthesis
TOP_N_PARENTS = 4
        