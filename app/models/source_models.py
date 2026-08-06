from pydantic import BaseModel
from typing import Optional

class SourceUploadResponse(BaseModel):
    status: str
    source_id: str
    job_id: Optional[str] = None
    message: str
    filename: Optional[str] = None

class SourceRenameSchema(BaseModel):
    filename: str