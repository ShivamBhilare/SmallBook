import os
import tempfile
from datetime import datetime, timezone
from celery import shared_task
from app.services.authentication.auth_service import get_service_role_client
from app.services.ingestion.extractor import pdf_extracter
from app.services.ingestion.chunker import HierarchicalChunker
from app.services.ingestion.qdrant_db import QdrantManager

@shared_task(name="process_pdf_task", bind=True)
def process_pdf_task(self, source_id: str, user_id: str):
    """The asynchronous background task for PDF RAG ingestion."""
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

        supabase.table("ingestion_jobs").update(update_payload).eq("source_id", source_id).execute()
        
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

        # 4. Extract Markdown (File handle closed first for Windows safety)
        md_text = pdf_extracter(tmp_pdf_path)
        if tmp_pdf_path and os.path.exists(tmp_pdf_path):
            os.remove(tmp_pdf_path)
            tmp_pdf_path = None

        # 5. Hierarchical Chunking
        chunker = HierarchicalChunker()
        # Linking chunks to the user's source document
        parents, children = chunker.chunk_document(md_text, notebook_id="pending", document_id=source_id)

        # 6. Save Parent Chunks to Supabase
        if parents:
            parent_records = [
                {
                    "id": p.id,
                    "source_id": p.document_id,
                    "chunk_text": p.text,
                    "chunk_index": p.order
                }
                for p in parents
            ]
            supabase.table("document_chunks").insert(parent_records).execute()

        # 7. Embed & Upload Child Chunks to Qdrant
        if children:
            qdrant = QdrantManager()
            qdrant.embed_and_upsert(children)

        # 8. Mark Job as Completed
        completed_iso = datetime.now(timezone.utc).isoformat()
        supabase.table("ingestion_jobs").update({
            "status": "completed",
            "completed_at": completed_iso
        }).eq("source_id", source_id).execute()
        supabase.table("sources").update({"ingestion_status": "completed"}).eq("id", source_id).execute()

    except Exception as e:
        if tmp_pdf_path and os.path.exists(tmp_pdf_path):
            try:
                os.remove(tmp_pdf_path)
            except Exception:
                pass

        # Log failure securely
        error_msg = str(e)
        supabase.table("ingestion_jobs").update({
            "status": "failed",
            "error_message": error_msg,
            "completed_at": datetime.now(timezone.utc).isoformat()
        }).eq("source_id", source_id).execute()
        supabase.table("sources").update({
            "ingestion_status": "failed",
            "ingestion_error": error_msg
        }).eq("id", source_id).execute()
        raise e