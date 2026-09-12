"""
Document Ingestion & Vector Indexing Subsystem

Coordinates text extraction from PDFs, hierarchical parent-child semantic chunking,
dense vector embedding generation, and Qdrant Cloud point upserts via asynchronous
Celery background worker pipelines.
"""
