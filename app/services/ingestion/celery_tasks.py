"""
Asynchronous PDF Ingestion & Indexing Celery Tasks

Defines the core background task `process_pdf_task` for end-to-end document processing:
    1. Downloads uploaded PDF from Supabase Storage to a secure temporary file.
    2. Extracts structured Markdown text and page count via PyMuPDF4LLM.
    3. Performs recursive hierarchical chunking into parent and child chunks.
    4. Persists parent chunks to Supabase PostgreSQL (`document_chunks`).
    5. Vectorizes child chunks and upserts points to Qdrant Cloud.
    6. Updates operational tracking tables (`ingestion_jobs` and `sources`).
"""

import os
import tempfile
from typing import Optional
from datetime import datetime, timezone
from celery import shared_task
from app.core.celery_app import celery_app
from app.services.authentication.auth_service import get_service_role_client
from app.services.ingestion.extractor import pdf_extracter
from app.services.ingestion.chunker import HierarchicalChunker
from app.services.ingestion.qdrant_db import QdrantManager


@shared_task(
    name="process_pdf_task",
    bind=True,
    max_retries=3,
    default_retry_delay=5
)
def process_pdf_task(self, source_id: str, user_id: Optional[str] = None):
    """
    Celery background worker task for complete PDF document ingestion.

    Coordinates document retrieval, Markdown extraction, parent-child token chunking,
    database chunk insertion, and vector database indexing.
    Safely deletes temporary files on both success and error branches.
    Automatically retries transient network/timeout errors with exponential backoff.

    Args:
        self: Bound Celery task instance for inspecting task ID and request state.
        source_id: UUID string of the target source document in the `sources` table.
        user_id: Optional UUID string of the document owner.

    Raises:
        Exception: Propagates extraction or database errors after updating job status to 'failed'.
    """
    supabase = get_service_role_client()
    tmp_pdf_path = None
    
    # Extract Celery Task ID if executing inside worker
    task_id = None
    if hasattr(self, "request") and getattr(self.request, "id", None):
        task_id = self.request.id
    
    try:
        # 1. Update job status to processing with started_at timestamp and task_id
        now_iso = datetime.now(timezone.utc).isoformat()
        update_payload = {
            "status": "processing",
            "started_at": now_iso
        }
        if task_id:
            update_payload["celery_task_id"] = task_id

        try:
            supabase.table("ingestion_jobs").update(update_payload).eq("source_id", source_id).execute()
        except Exception:
            pass
        
        # 2. Fetch file metadata
        source_res = supabase.table("sources").select("*").eq("id", source_id).execute()
        if not source_res.data:
            raise Exception("Source record not found in database.")
        source = source_res.data[0]
        storage_path = source["storage_path"]

        # 3. Download PDF from Supabase Storage to a temporary file
        with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp_file:
            pdf_bytes = supabase.storage.from_("user-documents").download(storage_path)
            tmp_file.write(pdf_bytes)
            tmp_pdf_path = tmp_file.name

        # 4. Extract Markdown and Page Count (File handle closed first for Windows safety)
        page_count = None
        try:
            import pymupdf
            with pymupdf.open(tmp_pdf_path) as doc:
                page_count = len(doc)
        except Exception:
            pass

        md_text = pdf_extracter(tmp_pdf_path)
        if tmp_pdf_path and os.path.exists(tmp_pdf_path):
            try:
                os.remove(tmp_pdf_path)
            except Exception:
                pass
            tmp_pdf_path = None

        # 5. Hierarchical Chunking
        chunker = HierarchicalChunker()
        # Linking chunks to the user's source document
        parents, children = chunker.chunk_document(md_text, notebook_id="pending", document_id=source_id)
        if not parents:
            raise ValueError("No extractable text content found in document. Please verify the PDF contains selectable text.")

        # 6. Save Parent Chunks to Supabase in Batches (ensure idempotence on retries)
        CHUNK_BATCH_SIZE = 250
        if parents:
            try:
                supabase.table("document_chunks").delete().eq("source_id", source_id).execute()
            except Exception:
                pass

            parent_records = [
                {
                    "id": p.id,
                    "source_id": p.document_id,
                    "chunk_text": p.text,
                    "chunk_index": p.order
                }
                for p in parents
            ]
            for i in range(0, len(parent_records), CHUNK_BATCH_SIZE):
                batch = parent_records[i : i + CHUNK_BATCH_SIZE]
                supabase.table("document_chunks").insert(batch).execute()

        # 7. Embed & Upload Child Chunks to Qdrant (with internal batching & retries)
        if children:
            qdrant = QdrantManager()
            qdrant.embed_and_upsert(children)

        # 8. Mark Job as Completed
        completed_iso = datetime.now(timezone.utc).isoformat()
        try:
            supabase.table("ingestion_jobs").update({
                "status": "completed",
                "completed_at": completed_iso,
                "error_message": None
            }).eq("source_id", source_id).execute()
        except Exception:
            pass
        
        source_update_payload = {"ingestion_status": "completed", "ingestion_error": None}
        if page_count is not None:
            source_update_payload["page_count"] = page_count
        try:
            supabase.table("sources").update(source_update_payload).eq("id", source_id).execute()
        except Exception:
            pass

    except Exception as e:
        if tmp_pdf_path and os.path.exists(tmp_pdf_path):
            try:
                os.remove(tmp_pdf_path)
            except Exception:
                pass

        error_msg = str(e)
        retries = getattr(self.request, "retries", 0) if hasattr(self, "request") else 0
        max_retries = getattr(self, "max_retries", 3)

        # If retries remain, attempt retry with exponential backoff
        if retries < max_retries:
            countdown = min(30, 2 ** retries * 3)
            try:
                supabase.table("ingestion_jobs").update({
                    "status": "processing",
                    "error_message": f"Retrying ({retries + 1}/{max_retries}) after: {error_msg}"
                }).eq("source_id", source_id).execute()
            except Exception:
                pass
            raise self.retry(exc=e, countdown=countdown)

        # All retries exhausted: mark permanently failed
        try:
            supabase.table("ingestion_jobs").update({
                "status": "failed",
                "error_message": error_msg,
                "completed_at": datetime.now(timezone.utc).isoformat()
            }).eq("source_id", source_id).execute()
        except Exception:
            pass

        try:
            supabase.table("sources").update({
                "ingestion_status": "failed",
                "ingestion_error": error_msg
            }).eq("id", source_id).execute()
        except Exception:
            pass
        raise e