"""
Notebook Workspace Data Models

Defines Pydantic schemas for managing notebook workspaces, which act as the root
container isolating user documents, vector collections, chat histories, and study sets.
"""

from datetime import datetime
from typing import Optional
from uuid import UUID
from pydantic import BaseModel, Field, ConfigDict


class NotebookCreateSchema(BaseModel):
    """
    Notebook Creation Payload.

    Validates title and optional default LLM provider configuration upon creating
    a new workspace.
    """
    title: str = Field(default="Untitled SmallBook", min_length=1, max_length=255)
    preferred_llm_provider: Optional[str] = None


class NotebookUpdateSchema(BaseModel):
    """
    Notebook Metadata Update Payload.

    Supports updating notebook title and preferred LLM provider routing.
    """
    title: Optional[str] = Field(None, min_length=1, max_length=255)
    preferred_llm_provider: Optional[str] = None


class NotebookResponseSchema(BaseModel):
    """
    Notebook Serialization Schema.

    Represents the complete database entity returned to API callers and Jinja2 templates,
    including UUID identifiers and timestamp metadata.
    """
    id: UUID
    user_id: UUID
    title: str
    preferred_llm_provider: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)