"""
Document Ingestion & Hierarchical Chunking Models

Defines internal data structures for the parent-child chunking pipeline.
In this architecture, larger ParentChunks provide extensive surrounding context
to the LLM prompt during synthesis, while smaller ChildChunks with dense vector
embeddings enable high-precision semantic similarity retrieval within Qdrant.
"""

from dataclasses import dataclass
from typing import Optional
import numpy as np


@dataclass
class ParentChunk:
    """
    Parent Text Chunk.

    Represents a macro-segment of a source document containing sufficient narrative
    context (typically 1000-2000 tokens) to serve as prompt grounding material.
    """
    id: str
    notebook_id: str
    document_id: str
    text: str
    order: int
    score: Optional[float] = 1.0


@dataclass
class ChildChunk:
    """
    Child Embedding Chunk.

    Represents a micro-segment (typically 200-400 tokens) linked to a ParentChunk.
    Child chunks are indexed in Qdrant with dense sentence-transformer embeddings
    for granular vector search matching.
    """
    id: str
    parent_id: str
    source_id: str
    text: str
    order: int
    embedding: Optional[np.ndarray] = None

