"""
Source Document Data Models

Defines Pydantic request and response schemas for document upload handoffs,
background ingestion job acknowledgments, and document renaming actions.
"""

from typing import Optional
from pydantic import BaseModel


class SourceUploadResponse(BaseModel):
    """
    Source Upload Acknowledgment Payload.

    Returned upon successful file ingestion dispatch, providing the client with
    the persisted source UUID, background Celery job tracking ID, and upload status.
    """
    status: str
    source_id: str
    job_id: Optional[str] = None
    message: str
    filename: Optional[str] = None


class SourceRenameSchema(BaseModel):
    """
    Source Rename Payload.

    Carries the updated human-readable filename for a source document.
    """
    filename: str