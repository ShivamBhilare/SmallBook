"""
SmallBook Business Services Layer

Contains domain-specific business logic, external API integrations, database workflows,
and asynchronous task orchestration across SmallBook subsystems:
    - `authentication`: Supabase Auth (GoTrue) integration and FastAPI security dependencies.
    - `notebooks`: Notebook workspace lifecycle and ownership boundaries.
    - `sources`: Document file upload deduplication, storage persistence, and library management.
    - `ingestion`: PDF extraction, hierarchical parent-child chunking, and Qdrant vector indexing.
    - `llm`: Bring-Your-Own-Key (BYOK) credential management and free-tier usage tracking.
    - `rag`: Semantic retrieval, citation augmentation, and cascading LiteLLM inference.
    - `chat`: Multi-turn chat session orchestration and branching history persistence.
    - `study`: Asynchronous flashcard and quiz generation, concurrency locks, and study notes.
"""
