# Model Configuration
ACTIVE_MODEL = "BAAI/bge-base-en-v1.5"
DEFAULT_BATCH_SIZE = 64

# Chunking Configuration
PARENT_CHUNK_TOKENS = 1000
PARENT_OVERLAP_TOKENS = 50
CHILD_CHUNK_TOKENS = 150
CHILD_OVERLAP_TOKENS = 25

# Retrieval Configuration
TOP_K_CHILDREN = 10
RELEVANCE_THRESHOLD = 0.35
NEIGHBOR_WINDOW = 1
CONTEXT_TOKEN_BUDGET = 5000
QUESTION_STARTERS = ("what", "why", "how", "when", "where", "who", "which", "is", "are", "does", "do", "can", "list")

# Reranker Model
CROSS_ENCODER_MODEL = "cross-encoder/ms-marco-MiniLM-L-6-v2"

# Hybrid & Rerank Configuration
TOP_K_HYBRID = 20       
RRF_K = 60               # Constant for Reciprocal Rank Fusion (60 is standard)
TOP_N_PARENTS = 4        