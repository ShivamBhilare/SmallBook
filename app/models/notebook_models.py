from datetime import datetime
from typing import Optional
from uuid import UUID
from pydantic import BaseModel, Field, ConfigDict


class NotebookCreateSchema(BaseModel):
    title: str = Field(default="Untitled SmallBook", min_length=1, max_length=255)
    preferred_llm_provider: Optional[str] = None


class NotebookUpdateSchema(BaseModel):
    title: Optional[str] = Field(None, min_length=1, max_length=255)
    preferred_llm_provider: Optional[str] = None


class NotebookResponseSchema(BaseModel):
    id: UUID
    user_id: UUID
    title: str
    preferred_llm_provider: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)