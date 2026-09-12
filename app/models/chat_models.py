"""
Chat & Grounded RAG Data Models

Defines Pydantic request and response schemas for interactive AI chat sessions,
including multi-turn prompt branching, source citation tracking, token metrics,
and historical message synchronization.
"""

from typing import Optional, List, Dict, Any
from pydantic import BaseModel


class ChatRequestSchema(BaseModel):
    """
    Chat Generation Request Payload.

    Represents an incoming user query submitted to the chat endpoint, specifying
    the target sources, prompting strategy, LLM model choice, response length,
    and optional parent message ID for conversation branching.
    """
    query: str
    source_ids: Optional[List[str]] = None
    mode: Optional[str] = "hybrid"  # "strict", "hybrid", "concise"
    model: Optional[str] = "gemini/gemini-2.5-flash"
    response_length: Optional[str] = "default"  # "default", "longer", "shorter"
    parent_id: Optional[str] = None  # Supports prompt branching & editing


class SourceCitationSchema(BaseModel):
    """
    Grounded Source Citation Metadata.

    Represents an individual source chunk retrieved from Qdrant and cited in the
    generated LLM response, including page number and relevance similarity score.
    """
    id: Optional[str] = None
    document_id: Optional[str] = None
    document_title: Optional[str] = None
    order: Optional[int] = 0
    text_snippet: Optional[str] = None
    chunk_id: Optional[str] = None
    page_number: Optional[int] = None
    relevance_score: Optional[float] = None


class ChatResponseSchema(BaseModel):
    """
    Complete Synchronous Chat Response.

    Returned when a non-streaming chat query finishes, packaging the full response text,
    cited sources, token consumption, and performance latency timings.
    """
    query: str
    answer: str
    mode: str
    sources: List[SourceCitationSchema]
    used_tokens: int
    timings_ms: Dict[str, Any] = {}


class CitationItemSchema(BaseModel):
    """
    Persisted Citation Item Schema.

    Represents a stored citation linked to a historical message record in the database.
    """
    id: Optional[str] = None
    chunk_id: Optional[str] = None
    source_title: str
    page_number: Optional[int] = None
    chunk_snapshot: Optional[str] = None
    relevance_score: Optional[float] = None
    created_at: Optional[str] = None


class ChatMessageResponseSchema(BaseModel):
    """
    Individual Chat Message Representation.

    Represents a persisted user or assistant message within a notebook's chat history,
    including provider/model metadata, branching pointer (`parent_id`), and attached citations.
    """
    id: str
    notebook_id: str
    parent_id: Optional[str] = None
    role: str
    content: str
    llm_provider: Optional[str] = None
    llm_model: Optional[str] = None
    is_summarized: Optional[bool] = False
    created_at: str
    citations: Optional[List[CitationItemSchema]] = []


class ChatHistoryResponseSchema(BaseModel):
    """
    Chat Message History Collection.

    Wraps the chronologically ordered list of messages belonging to an active notebook session.
    """
    messages: List[ChatMessageResponseSchema]


