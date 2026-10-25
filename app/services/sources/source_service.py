"""
Source Document Management & Storage Pipeline Service

Orchestrates source document uploads, cryptographic SHA-256 deduplication,
Supabase Storage bucket operations, and background ingestion job scheduling.
Provides document cross-notebook linking, renaming, unlinking, and deep cascading
resource deletion (Storage files, Celery tasks, parent chunks, and Qdrant vectors).
"""

import hashlib
import logging
import uuid
from typing import Optional
from fastapi import UploadFile, HTTPException, status, BackgroundTasks
from supabase import Client

logger = logging.getLogger(__name__)

# Maximum permissible document upload size (50 MB) to safeguard server memory during extraction
MAX_FILE_SIZE = 50 * 1024 * 1024 
STORAGE_BUCKET = "user-documents"


def _run_process_pdf_fallback(source_id: str, user_id: str):
    """Executes process_pdf_task directly when Celery broker is unreachable."""
    try:
        from app.services.ingestion.celery_tasks import process_pdf_task
        process_pdf_task.apply(args=[source_id, user_id])
    except Exception as err:
        logger.error(f"Fallback direct execution of process_pdf_task failed for source {source_id}: {err}")


# =========================================================================
# 1. ASYNCHRONOUS STORAGE & CELERY DISPATCH WORKERS
# =========================================================================

def _async_storage_upload_and_trigger_celery(
    storage_path: str,
    file_bytes: bytes,
    source_id: str,
    user_id: str,
    job_id: Optional[str]
):
    """
    Background worker function for asynchronous file persistence and task dispatch.

    Executes outside the main HTTP request-response cycle via FastAPI BackgroundTasks:
    1. Uploads the raw PDF bytes into the Supabase Storage bucket (`user-documents`).
    2. Enqueues the `process_pdf_task` Celery background ingestion task.
    3. Falls back to immediate in-process task execution if Redis/Celery is unreachable.

    Args:
        storage_path: Target path in Supabase Storage (e.g. `{user_id}/{source_id}.pdf`).
        file_bytes: Raw binary PDF payload.
        source_id: UUID of the source document database record.
        user_id: UUID of the owning user.
        job_id: Optional UUID of the associated `ingestion_jobs` tracker record.
    """
    # 1. Supabase Storage Upload via privileged service role client with retries
    upload_success = False
    last_upload_err = None
    from app.services.authentication.auth_service import get_service_role_client
    service_client = get_service_role_client()

    import time
    for attempt in range(1, 4):
        try:
            service_client.storage.from_(STORAGE_BUCKET).upload(
                path=storage_path, 
                file=file_bytes, 
                file_options={"content-type": "application/pdf"}
            )
            upload_success = True
            break
        except Exception as e:
            last_upload_err = e
            logger.warning(f"Storage upload attempt {attempt}/3 failed for source {source_id}: {e}")
            if attempt < 3:
                time.sleep(1.5 * attempt)

    if not upload_success:
        err_msg = f"Storage upload failed after retries: {str(last_upload_err)}"
        logger.error(err_msg)
        try:
            from datetime import datetime, timezone
            service_client.table("ingestion_jobs").update({
                "status": "failed",
                "error_message": err_msg,
                "completed_at": datetime.now(timezone.utc).isoformat()
            }).eq("source_id", source_id).execute()
            service_client.table("sources").update({
                "ingestion_status": "failed",
                "ingestion_error": err_msg
            }).eq("id", source_id).execute()
        except Exception as db_err:
            logger.error(f"Failed to record storage upload failure in database: {db_err}")
        return

    # 2. Celery Handoff (Asynchronous Processing with Direct Fallback)
    try:
        from app.services.ingestion.celery_tasks import process_pdf_task
        celery_task = process_pdf_task.apply_async(
            args=[source_id, user_id],
            connect_timeout=10,
            retry=True
        )

        # Update the job tracker with the actual Celery Task ID
        if getattr(celery_task, "id", None):
            if job_id:
                service_client.table("ingestion_jobs").update({"celery_task_id": celery_task.id}).eq("id", job_id).execute()
            service_client.table("ingestion_jobs").update({"celery_task_id": celery_task.id}).eq("source_id", source_id).execute()
    except Exception as e:
        logger.warning(f"Redis/Celery connection failed ({e}). Falling back to direct background thread execution...")
        _run_process_pdf_fallback(source_id, user_id)


# =========================================================================
# 2. SOURCE UPLOAD & DEDUPLICATION
# =========================================================================

def handle_source_upload(
    client: Client, 
    user_id: str, 
    notebook_id: str, 
    file: UploadFile,
    background_tasks: BackgroundTasks,
    file_bytes: Optional[bytes] = None
) -> dict:
    """
    Validates, deduplicates, and initiates the ingestion pipeline for a new document.

    Checks:
    1. Enforces PDF MIME type and 50MB file size limits.
    2. Computes SHA-256 hash of file bytes for instant user-level deduplication.
    3. If identical file was previously uploaded by this user, links the existing
       source to the target notebook without re-uploading or re-embedding.
    4. If new, inserts source record, creates initial ingestion job tracker,
       and delegates storage upload and Celery processing to background tasks.

    Args:
        client: Active per-request Supabase client.
        user_id: UUID string of the uploading user.
        notebook_id: UUID string of the target notebook workspace.
        file: UploadFile object from FastAPI endpoint.
        background_tasks: FastAPI BackgroundTasks registry.
        file_bytes: Optional pre-read binary content bytes.

    Returns:
        dict: Acknowledgment payload with status ('processing' or 'linked_existing') and IDs.

    Raises:
        HTTPException: 400 Bad Request if file is non-PDF or exceeds 50MB.
        HTTPException: 500 Internal Server Error if database insertion fails.
    """
    # 1. Validation
    if file.content_type != "application/pdf":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Only PDF files are supported.")
    
    if file_bytes is None:
        file_bytes = file.file.read()
    file_size = len(file_bytes)
    
    if file_size > MAX_FILE_SIZE:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="File size exceeds the 50MB limit.")

    # 2. Content Hashing (The Deduplication Check)
    content_hash = hashlib.sha256(file_bytes).hexdigest()

    # 3. Cross-Notebook Asset Check
    # Does this specific user already have a source with this identical hash?
    existing_response = client.table("sources").select("*").eq("user_id", user_id).eq("content_hash", content_hash).execute()

    if existing_response.data:
        # Scenario A: File already exists in the system for this user.
        source = existing_response.data[0]
        source_id = source["id"]
        
        # Check if it's already linked to THIS notebook
        link_response = client.table("notebook_sources").select("*").eq("notebook_id", notebook_id).eq("source_id", source_id).execute()
        
        if not link_response.data:
            # Create the link without re-uploading or re-embedding!
            client.table("notebook_sources").insert({
                "notebook_id": notebook_id, 
                "source_id": source_id
            }).execute()
            
        return {
            "status": "linked_existing", 
            "source_id": source_id, 
            "job_id": None,
            "message": "File identical to a previous upload. Successfully linked to notebook without re-processing.",
            "filename": file.filename
        }

    # Scenario B: New File
    file_uuid = str(uuid.uuid4())
    # Secure storage path using the user's ID as the root folder
    storage_path = f"{user_id}/{file_uuid}.pdf"

    # Database Insertion
    source_data = {
        "id": file_uuid,
        "user_id": user_id,
        "original_filename": file.filename,
        "storage_path": storage_path,
        "file_size_bytes": file_size,
        "content_hash": content_hash,
        "ingestion_status": "pending"
    }
    
    source_res = client.table("sources").insert(source_data).execute()
    if not source_res.data:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to create source database record.")
    
    source_id = source_res.data[0]["id"]

    # Link the new source to the notebook
    client.table("notebook_sources").insert({
        "notebook_id": notebook_id, 
        "source_id": source_id
    }).execute()

    # Initialize Job Tracker
    job_res = client.table("ingestion_jobs").insert({
        "source_id": source_id,
        "status": "queued"
    }).execute()
    
    job_id = job_res.data[0]["id"] if job_res.data else None

    # Schedule heavy storage upload and Celery task dispatch in background
    background_tasks.add_task(
        _async_storage_upload_and_trigger_celery,
        storage_path=storage_path,
        file_bytes=file_bytes,
        source_id=source_id,
        user_id=user_id,
        job_id=job_id
    )

    return {
        "status": "processing",
        "source_id": source_id,
        "job_id": job_id,
        "message": "File uploaded and queued for processing.",
        "filename": file.filename
    }


# =========================================================================
# 3. SOURCE RETRIEVAL & NOTEBOOK LINKING
# =========================================================================

def get_notebook_sources(client: Client, notebook_id: str) -> list[dict]:
    """
    Retrieves all source documents actively attached to a given notebook workspace.

    Args:
        client: Active Supabase client.
        notebook_id: UUID string of the target notebook.

    Returns:
        list[dict]: List of source document dictionaries.
    """
    try:
        ns_res = client.table("notebook_sources").select("source_id").eq("notebook_id", notebook_id).execute()
        if not ns_res.data:
            return []
        
        source_ids = [row["source_id"] for row in ns_res.data if row.get("source_id")]
        if not source_ids:
            return []
            
        s_res = client.table("sources").select("*").in_("id", source_ids).execute()
        return s_res.data or []
    except Exception as e:
        print(f"Error fetching notebook sources: {e}")
        return []


def get_all_user_sources(client: Client, user_id: str) -> list[dict]:
    """
    Retrieves all source documents owned by the user across the entire library.

    Annotates each source dictionary with a `notebooks` list showing which notebook
    workspaces currently reference this document.

    Args:
        client: Active Supabase client.
        user_id: UUID string of the authenticated user.

    Returns:
        list[dict]: List of all user source dictionaries with notebook attachment metadata.
    """
    try:
        try:
            s_res = client.table("sources").select("*").eq("user_id", user_id).order("created_at", desc=True).execute()
        except Exception:
            s_res = client.table("sources").select("*").eq("user_id", user_id).execute()

        sources = s_res.data or []
        if not sources:
            return []

        source_ids = [s["id"] for s in sources]
        ns_res = client.table("notebook_sources").select("source_id, notebook_id").in_("source_id", source_ids).execute()
        ns_data = ns_res.data or []

        notebook_ids = list(set([row["notebook_id"] for row in ns_data if row.get("notebook_id")]))
        
        notebook_map = {}
        if notebook_ids:
            nb_res = client.table("notebooks").select("id, title").eq("user_id", user_id).in_("id", notebook_ids).execute()
            for nb in (nb_res.data or []):
                notebook_map[nb["id"]] = nb["title"]

        source_notebooks_map = {}
        for row in ns_data:
            sid = row["source_id"]
            nid = row["notebook_id"]
            if nid in notebook_map:
                if sid not in source_notebooks_map:
                    source_notebooks_map[sid] = []
                source_notebooks_map[sid].append({"id": nid, "title": notebook_map[nid]})

        for s in sources:
            s["notebooks"] = source_notebooks_map.get(s["id"], [])

        return sources
    except Exception as e:
        print(f"Error fetching all user sources: {e}")
        return []


def rename_source(client: Client, user_id: str, source_id: str, new_filename: str) -> dict:
    """
    Renames a source document's display filename.

    Args:
        client: Active Supabase client.
        user_id: UUID string of the requesting user.
        source_id: UUID string of the target source.
        new_filename: New human-readable filename string.

    Returns:
        dict: The updated source database record.

    Raises:
        HTTPException: 400 Bad Request if filename is empty.
        HTTPException: 404 Not Found if source not found or user lacks permission.
    """
    if not new_filename or not new_filename.strip():
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Filename cannot be empty.")
        
    res = client.table("sources").update({"original_filename": new_filename.strip()}).eq("id", source_id).eq("user_id", user_id).execute()
    if not res.data:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Source not found or permission denied.")
        
    return res.data[0]


def link_sources_to_notebook(client: Client, user_id: str, notebook_id: str, source_ids: list[str]) -> list[dict]:
    """
    Attaches existing library sources owned by the user to the specified notebook workspace.

    Filters out sources that are already linked to avoid duplicate entries in `notebook_sources`.

    Args:
        client: Active Supabase client.
        user_id: UUID string of the authenticated user.
        notebook_id: UUID string of the target notebook.
        source_ids: List of source UUID strings to attach.

    Returns:
        list[dict]: List of newly linked source records.

    Raises:
        HTTPException: 404 Not Found if the notebook is not found or access is denied.
    """
    if not source_ids:
        return []

    # 1. Verify notebook access
    nb = client.table("notebooks").select("id").eq("id", notebook_id).eq("user_id", user_id).execute()
    if not nb.data:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Notebook not found or permission denied.")

    # 2. Verify source ownership
    s_res = client.table("sources").select("*").eq("user_id", user_id).in_("id", source_ids).execute()
    valid_sources = s_res.data or []
    if not valid_sources:
        return []

    valid_source_ids = [s["id"] for s in valid_sources]

    # 3. Check existing notebook_sources links
    ns_res = client.table("notebook_sources").select("source_id").eq("notebook_id", notebook_id).in_("source_id", valid_source_ids).execute()
    existing_linked = set([r["source_id"] for r in (ns_res.data or [])])

    to_link_ids = [sid for sid in valid_source_ids if sid not in existing_linked]

    if to_link_ids:
        insert_rows = [{"notebook_id": notebook_id, "source_id": sid} for sid in to_link_ids]
        client.table("notebook_sources").insert(insert_rows).execute()

    newly_linked_sources = [s for s in valid_sources if s["id"] in to_link_ids]
    return newly_linked_sources


def remove_source_from_notebook(client: Client, user_id: str, notebook_id: str, source_id: str) -> bool:
    """
    Unlinks a source document from a specific notebook workspace.

    Does not delete the source from the user's global library or remove vector embeddings.

    Args:
        client: Active Supabase client.
        user_id: UUID string of the authenticated user.
        notebook_id: UUID string of the notebook workspace.
        source_id: UUID string of the source document to detach.

    Returns:
        bool: True upon successful removal.

    Raises:
        HTTPException: 404 Not Found if notebook is not found or access is denied.
    """
    # 1. Verify notebook access
    nb = client.table("notebooks").select("id").eq("id", notebook_id).eq("user_id", user_id).execute()
    if not nb.data:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Notebook not found or access denied.")

    # 2. Delete notebook_sources link
    client.table("notebook_sources").delete().eq("notebook_id", notebook_id).eq("source_id", source_id).execute()

    return True


# =========================================================================
# 4. PERMANENT SOURCE DELETION & CASCADING CLEANUP
# =========================================================================

def _async_cleanup_source_resources(storage_path: Optional[str], source_id: str):
    """
    Background worker to asynchronously clean up heavy external resources:
    1. Revokes active Celery tasks and deletes `ingestion_jobs` records.
    2. Deletes parent chunk text records from `document_chunks` table.
    3. Removes original PDF file from Supabase storage bucket.
    4. Deletes child chunk vector points from Qdrant Cloud.

    Args:
        storage_path: Path to the PDF file in Supabase Storage.
        source_id: UUID string of the deleted source document.
    """
    from app.services.authentication.auth_service import get_service_role_client
    service_client = get_service_role_client()

    # 1. Revoke active Celery tasks and clean ingestion_jobs
    try:
        jobs_res = service_client.table("ingestion_jobs").select("celery_task_id").eq("source_id", source_id).execute()
        if jobs_res.data:
            for job in jobs_res.data:
                task_id = job.get("celery_task_id")
                if task_id:
                    try:
                        from app.core.celery_app import celery_app
                        celery_app.control.revoke(task_id, terminate=True)
                        print(f"🛑 Revoked celery task {task_id} for deleted source {source_id}")
                    except Exception as e:
                        print(f"⚠️ Warning: Could not revoke celery task {task_id}: {e}")
        service_client.table("ingestion_jobs").delete().eq("source_id", source_id).execute()
    except Exception as e:
        print(f"⚠️ Error cleaning ingestion jobs for source {source_id}: {e}")

    # 2. Delete parent chunks from document_chunks
    try:
        service_client.table("document_chunks").delete().eq("source_id", source_id).execute()
    except Exception as e:
        print(f"⚠️ Error removing document_chunks for source {source_id}: {e}")

    # 3. Delete file from Supabase storage bucket
    if storage_path:
        try:
            service_client.storage.from_(STORAGE_BUCKET).remove([storage_path])
        except Exception as e:
            print(f"⚠️ Warning: Failed to remove storage file {storage_path}: {e}")

    # 4. Remove vectors from Qdrant Cloud
    try:
        from app.services.ingestion.qdrant_db import QdrantManager
        q_mgr = QdrantManager()
        q_mgr.delete_by_source_id(source_id)
    except Exception as e:
        print(f"⚠️ Warning: Failed to remove vectors from Qdrant for source {source_id}: {e}")


def delete_source_permanently(
    client: Client, 
    user_id: str, 
    source_id: str, 
    background_tasks: Optional[BackgroundTasks] = None
) -> bool:
    """
    Permanently deletes a source document and cascades cleanup across all systems.

    Synchronously removes database rows from `notebook_sources` and `sources` so the UI
    updates immediately, then delegates heavy external resource deletion (Storage,
    Celery task revocation, Qdrant vectors, and PostgreSQL chunks) to background tasks.

    Args:
        client: Active Supabase client.
        user_id: UUID string of the authenticated owner.
        source_id: UUID string of the source to delete.
        background_tasks: Optional FastAPI BackgroundTasks registry.

    Returns:
        bool: True upon successful deletion.

    Raises:
        HTTPException: 404 Not Found if source not found or permission denied.
    """
    # 1. Fetch source record to verify ownership and get storage path
    src_res = client.table("sources").select("id, storage_path").eq("id", source_id).eq("user_id", user_id).execute()
    if not src_res.data:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Source not found or permission denied.")

    source = src_res.data[0]
    storage_path = source.get("storage_path")

    # 2. Synchronously delete notebook links
    client.table("notebook_sources").delete().eq("source_id", source_id).execute()

    # 3. Synchronously delete source record so it instantly disappears from UI
    client.table("sources").delete().eq("id", source_id).eq("user_id", user_id).execute()

    # 4. Offload heavy storage, Celery task revocation, document chunks & Qdrant vector deletion to background
    if background_tasks is not None:
        background_tasks.add_task(_async_cleanup_source_resources, storage_path, source_id)
    else:
        _async_cleanup_source_resources(storage_path, source_id)

    return True


def retry_source_ingestion(
    client: Client,
    user_id: str,
    notebook_id: str,
    source_id: str,
    background_tasks: Optional[BackgroundTasks] = None
) -> dict:
    """
    Restarts background extraction and vectorization for a failed or stalled source document.

    Resets the ingestion status and error messages, and re-enqueues the Celery processing task.

    Args:
        client: Active Supabase client.
        user_id: UUID of the requesting owner.
        notebook_id: UUID of the notebook workspace.
        source_id: UUID of the document to retry.
        background_tasks: Optional FastAPI BackgroundTasks registry.

    Returns:
        dict: Acknowledgment payload with status 'queued'.

    Raises:
        HTTPException: 404 if source not found or unauthorized.
    """
    src_res = client.table("sources").select("*").eq("id", source_id).eq("user_id", user_id).execute()
    if not src_res.data:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Source not found or permission denied.")

    # 1. Reset status in DB
    client.table("sources").update({
        "ingestion_status": "pending",
        "ingestion_error": None
    }).eq("id", source_id).execute()

    client.table("ingestion_jobs").update({
        "status": "queued",
        "error_message": None
    }).eq("source_id", source_id).execute()

    # 2. Dispatch task
    try:
        from app.services.ingestion.celery_tasks import process_pdf_task
        task = process_pdf_task.apply_async(args=[source_id, user_id], connect_timeout=10, retry=True)
        if getattr(task, "id", None):
            client.table("ingestion_jobs").update({"celery_task_id": task.id}).eq("source_id", source_id).execute()
    except Exception as e:
        print(f"⚠️ Redis/Celery connection failed on retry ({e}). Falling back to background task...")
        from app.services.ingestion.celery_tasks import process_pdf_task
        if background_tasks is not None:
            background_tasks.add_task(process_pdf_task.apply, args=[source_id, user_id])
        else:
            process_pdf_task.apply(args=[source_id, user_id])

    return {
        "status": "queued",
        "source_id": source_id,
        "message": "Ingestion retry initiated."
    }
