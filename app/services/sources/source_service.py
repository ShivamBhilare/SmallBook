import hashlib
import uuid
from typing import Optional
from fastapi import UploadFile, HTTPException, status, BackgroundTasks
from supabase import Client

# 50 MB limit to protect memory during extraction
MAX_FILE_SIZE = 50 * 1024 * 1024 
STORAGE_BUCKET = "user-documents"

def _async_storage_upload_and_trigger_celery(
    client: Client,
    storage_path: str,
    file_bytes: bytes,
    source_id: str,
    user_id: str,
    job_id: Optional[str]
):
    """
    Background task worker function to handle synchronous Supabase storage upload 
    and dispatch the Celery ingestion job without blocking the HTTP request.
    """
    # 1. Storage Upload
    try:
        client.storage.from_(STORAGE_BUCKET).upload(
            path=storage_path, 
            file=file_bytes, 
            file_options={"content-type": "application/pdf"}
        )
    except Exception as e:
        print(f"❌ Background storage upload failed for source {source_id}: {e}")
        return

    # 2. Celery Handoff (Asynchronous Processing)
    try:
        from app.core.celery_app import process_pdf_task
        celery_task = process_pdf_task.delay(source_id, user_id)

        # Update the job tracker with the actual Celery Task ID
        if job_id and getattr(celery_task, "id", None):
            client.table("ingestion_jobs").update({"celery_task_id": celery_task.id}).eq("id", job_id).execute()
    except Exception as e:
        print(f"⚠️ Warning: Redis/Celery connection failed. File saved, but task not dispatched. Error: {e}")

def handle_source_upload(
    client: Client, 
    user_id: str, 
    notebook_id: str, 
    file: UploadFile,
    background_tasks: BackgroundTasks
) -> dict:
    """
    Handles file validation, hashing, DB tracking, and delegates heavy storage upload & Celery dispatch to BackgroundTask.
    """
    # 1. Validation
    if file.content_type != "application/pdf":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Only PDF files are supported.")
    
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
        client=client,
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

def get_notebook_sources(client: Client, notebook_id: str) -> list[dict]:
    """
    Retrieves all source documents linked to a given notebook.
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

def rename_source(client: Client, user_id: str, source_id: str, new_filename: str) -> dict:
    """
    Renames a source document for a user.
    """
    if not new_filename or not new_filename.strip():
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Filename cannot be empty.")
        
    res = client.table("sources").update({"original_filename": new_filename.strip()}).eq("id", source_id).eq("user_id", user_id).execute()
    if not res.data:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Source not found or permission denied.")
        
    return res.data[0]

def remove_source_from_notebook(client: Client, user_id: str, notebook_id: str, source_id: str) -> bool:
    """
    Unlinks a source document from a specific notebook.
    """
    # 1. Verify notebook access
    nb = client.table("notebooks").select("id").eq("id", notebook_id).execute()
    if not nb.data:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Notebook not found or access denied.")

    # 2. Delete notebook_sources link
    client.table("notebook_sources").delete().eq("notebook_id", notebook_id).eq("source_id", source_id).execute()

    return True

def delete_source_permanently(client: Client, user_id: str, source_id: str) -> bool:
    """
    Permanently deletes a source document from everywhere:
    removes storage file, all notebook links, ingestion jobs, and DB row.
    """
    # Fetch source record
    src_res = client.table("sources").select("*").eq("id", source_id).eq("user_id", user_id).execute()
    if not src_res.data:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Source not found or permission denied.")

    source = src_res.data[0]
    storage_path = source.get("storage_path")

    # 1. Remove file from Supabase storage bucket
    if storage_path:
        try:
            client.storage.from_(STORAGE_BUCKET).remove([storage_path])
        except Exception as e:
            print(f"⚠️ Warning: Failed to remove storage file {storage_path}: {e}")

    # 2. Delete all links in notebook_sources
    client.table("notebook_sources").delete().eq("source_id", source_id).execute()

    # 3. Delete from ingestion_jobs
    client.table("ingestion_jobs").delete().eq("source_id", source_id).execute()

    # 4. Delete source record
    client.table("sources").delete().eq("id", source_id).eq("user_id", user_id).execute()

    return True