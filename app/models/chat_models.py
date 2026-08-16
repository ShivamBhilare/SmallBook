from typing import Optional, List, Dict, Any
from pydantic import BaseModel

class ChatRequestSchema(BaseModel):
    query: str
    source_ids: Optional[List[str]] = None
    mode: Optional[str] = "hybrid"  # "strict", "hybrid", "concise"
    model: Optional[str] = "gemini/gemini-2.5-flash"
    response_length: Optional[str] = "default"  # "default", "longer", "shorter"
    parent_id: Optional[str] = None  # Supports prompt branching & editing

class SourceCitationSchema(BaseModel):
    id: Optional[str] = None
    document_id: Optional[str] = None
    document_title: Optional[str] = None
    order: Optional[int] = 0
    text_snippet: Optional[str] = None
    chunk_id: Optional[str] = None
    page_number: Optional[int] = None
    relevance_score: Optional[float] = None

class ChatResponseSchema(BaseModel):
    query: str
    answer: str
    mode: str
    sources: List[SourceCitationSchema]
    used_tokens: int
    timings_ms: Dict[str, Any] = {}

class CitationItemSchema(BaseModel):
    id: Optional[str] = None
    chunk_id: Optional[str] = None
    source_title: str
    page_number: Optional[int] = None
    chunk_snapshot: Optional[str] = None
    relevance_score: Optional[float] = None
    created_at: Optional[str] = None

class ChatMessageResponseSchema(BaseModel):
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
    messages: List[ChatMessageResponseSchema]

