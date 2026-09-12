"""Source Documents Router Module.

Exposes endpoints for uploading PDF files to notebooks, monitoring ingestion progress,
linking cross-notebook library sources, renaming documents, unlinking sources from
individual workspaces, and permanently deleting documents from Supabase Storage and Qdrant.
"""

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    File,
    HTTPException,
    Response,
    UploadFile,
)
from supabase import Client

from app.models.source_models import SourceRenameSchema, SourceUploadResponse
from app.services.authentication.auth_service import get_supabase_client, login_required
from app.services.sources import source_service

# Router scoped to specific notebook workspaces
router = APIRouter(prefix="/notebooks/{notebook_id}/sources", tags=["Sources"])


@router.post("/upload", response_model=SourceUploadResponse, status_code=202)
async def upload_source(
    notebook_id: str,
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    user=Depends(login_required),
    client: Client = Depends(get_supabase_client)
):
    """Handles PDF file uploads to a specific notebook workspace.

    Verifies user ownership of the notebook, detects duplicates via SHA-256 hash,
    stores the raw file in Supabase Storage, creates metadata records, and enqueues
    asynchronous Celery ingestion tasks.

    Args:
        notebook_id: UUID of the workspace notebook.
        background_tasks: FastAPI background task manager.
        file: UploadFile instance containing PDF binary stream.
        user: Authenticated user object from dependency.
        client: Supabase client instance.

    Returns:
        SourceUploadResponse with HTTP 202 Accepted status.

    Raises:
        HTTPException: 404 if notebook not found or unauthorized.
    """
    # 1. RLS verifies notebook ownership implicitly during DB insertion, but we double check here
    # to prevent users uploading to notebooks they don't own.
    notebook_check = client.table("notebooks").select("id").eq("id", notebook_id).eq("user_id", user.id).execute()
    if not notebook_check.data:
        raise HTTPException(status_code=404, detail="Notebook not found or access denied.")

    # 2. Handoff to service layer
    file_bytes = await file.read()
    result = source_service.handle_source_upload(
        client=client,
        user_id=user.id,
        notebook_id=notebook_id,
        file=file,
        background_tasks=background_tasks,
        file_bytes=file_bytes
    )

    return result


@router.get("/list", response_model=dict)
@router.get("", response_model=dict)
def get_notebook_sources_endpoint(
    notebook_id: str,
    user=Depends(login_required),
    client: Client = Depends(get_supabase_client)
):
    """Fetches all source documents linked to a specific notebook workspace.

    Args:
        notebook_id: UUID of the notebook.
        user: Authenticated user object from dependency.
        client: Supabase client instance.

    Returns:
        Dictionary containing 'sources' list.

    Raises:
        HTTPException: 404 if notebook not found or unauthorized.
    """
    notebook_check = client.table("notebooks").select("id").eq("id", notebook_id).eq("user_id", user.id).execute()
    if not notebook_check.data:
        raise HTTPException(status_code=404, detail="Notebook not found or access denied.")
    sources = source_service.get_notebook_sources(client, notebook_id)
    return {"sources": sources}


@router.get("/library", response_model=dict)
def get_library_sources(
    notebook_id: str,
    user=Depends(login_required),
    client: Client = Depends(get_supabase_client)
):
    """Fetches all PDF sources uploaded by the user across all notebooks for cross-linking.

    Args:
        notebook_id: UUID of the requesting notebook.
        user: Authenticated user object from dependency.
        client: Supabase client instance.

    Returns:
        Dictionary containing 'sources' list from the user's master library.

    Raises:
        HTTPException: 404 if notebook not found or unauthorized.
    """
    notebook_check = client.table("notebooks").select("id").eq("id", notebook_id).eq("user_id", user.id).execute()
    if not notebook_check.data:
        raise HTTPException(status_code=404, detail="Notebook not found or access denied.")
    sources = source_service.get_all_user_sources(client, user.id)
    return {"sources": sources}


@router.post("/link", response_model=dict)
def link_existing_sources(
    notebook_id: str,
    payload: dict,
    user=Depends(login_required),
    client: Client = Depends(get_supabase_client)
):
    """Links existing source documents from the user's library to this notebook.

    Args:
        notebook_id: UUID of the target notebook.
        payload: Dictionary containing 'source_ids' list.
        user: Authenticated user object from dependency.
        client: Supabase client instance.

    Returns:
        Dictionary with status and linked_sources list.

    Raises:
        HTTPException: 400 if no source IDs provided.
    """
    source_ids = payload.get("source_ids", [])
    if not source_ids:
        raise HTTPException(status_code=400, detail="No source IDs provided.")

    linked_sources = source_service.link_sources_to_notebook(client, user.id, notebook_id, source_ids)
    return {"status": "success", "linked_sources": linked_sources}


@router.patch("/{source_id}/rename", response_model=dict)
def rename_source(
    notebook_id: str,
    source_id: str,
    payload: SourceRenameSchema,
    user=Depends(login_required),
    client: Client = Depends(get_supabase_client)
):
    """Renames a source document's displayed original filename.

    Args:
        notebook_id: UUID of the notebook.
        source_id: UUID of the source to rename.
        payload: SourceRenameSchema with new filename.
        user: Authenticated user object from dependency.
        client: Supabase client instance.

    Returns:
        Dictionary with status and updated source object.

    Raises:
        HTTPException: 404 if notebook not found.
    """
    nb_check = client.table("notebooks").select("id").eq("id", notebook_id).eq("user_id", user.id).execute()
    if not nb_check.data:
        raise HTTPException(status_code=404, detail="Notebook not found or access denied.")

    updated_source = source_service.rename_source(client, user.id, source_id, payload.filename)
    return {"status": "success", "source": updated_source}


@router.get("/{source_id}/status", response_model=dict)
def get_source_status(
    notebook_id: str,
    source_id: str,
    user=Depends(login_required),
    client: Client = Depends(get_supabase_client)
):
    """Retrieves the background ingestion processing status for a source document.

    Args:
        notebook_id: UUID of the notebook.
        source_id: UUID of the source document.
        user: Authenticated user object from dependency.
        client: Supabase client instance.

    Returns:
        Dictionary containing current 'status' string (e.g., 'processing', 'completed', 'failed').

    Raises:
        HTTPException: 404 if notebook, source, or job record not found.
    """
    nb_check = client.table("notebooks").select("id").eq("id", notebook_id).eq("user_id", user.id).execute()
    if not nb_check.data:
        raise HTTPException(status_code=404, detail="Notebook not found or access denied.")

    src_check = client.table("sources").select("id").eq("id", source_id).eq("user_id", user.id).execute()
    if not src_check.data:
        raise HTTPException(status_code=404, detail="Source not found or access denied.")

    job_res = client.table("ingestion_jobs").select("*").eq("source_id", source_id).execute()
    if not job_res.data:
        raise HTTPException(status_code=404, detail="Status not found for this source.")

    return {"status": job_res.data[0].get("status", "unknown")}


@router.delete("/{source_id}", status_code=204)
def remove_source(
    notebook_id: str,
    source_id: str,
    background_tasks: BackgroundTasks,
    mode: str = "notebook",
    user=Depends(login_required),
    client: Client = Depends(get_supabase_client)
):
    """Removes a source document.

    Supports two modes:
      - 'notebook': Unlinks source from this workspace while retaining it in the user's library.
      - 'library': Permanently deletes the document from storage, Qdrant vectors, and all notebooks.

    Args:
        notebook_id: UUID of the active notebook.
        source_id: UUID of the source document.
        background_tasks: Background task manager for vector point deletion.
        mode: Removal scope ('notebook' or 'library').
        user: Authenticated user object from dependency.
        client: Supabase client instance.

    Returns:
        HTTP 204 No Content Response.

    Raises:
        HTTPException: 404 if notebook not found.
    """
    nb_check = client.table("notebooks").select("id").eq("id", notebook_id).eq("user_id", user.id).execute()
    if not nb_check.data:
        raise HTTPException(status_code=404, detail="Notebook not found or access denied.")

    if mode == "library":
        source_service.delete_source_permanently(client, user.id, source_id, background_tasks)
    else:
        source_service.remove_source_from_notebook(client, user.id, notebook_id, source_id)
    return Response(status_code=204)


# ==============================================================================
# GLOBAL SOURCES ROUTER (Cross-notebook library operations)
# ==============================================================================

global_sources_router = APIRouter(prefix="/api/sources", tags=["Global Sources"])


@global_sources_router.get("/all", response_model=dict)
def get_all_sources(
    user=Depends(login_required),
    client: Client = Depends(get_supabase_client)
):
    """Fetches all PDF sources uploaded by the authenticated user across all notebooks.

    Args:
        user: Authenticated user object from dependency.
        client: Supabase client instance.

    Returns:
        Dictionary containing user's master 'sources' list.
    """
    sources = source_service.get_all_user_sources(client, user.id)
    return {"sources": sources}


@global_sources_router.delete("/{source_id}", status_code=204)
def delete_source_permanently_endpoint(
    source_id: str,
    background_tasks: BackgroundTasks,
    user=Depends(login_required),
    client: Client = Depends(get_supabase_client)
):
    """Permanently deletes a source document from everywhere (Storage, Qdrant, DB).

    Args:
        source_id: UUID of the source document to delete.
        background_tasks: Background task manager for Qdrant deletion.
        user: Authenticated user object from dependency.
        client: Supabase client instance.

    Returns:
        HTTP 204 No Content Response.
    """
    source_service.delete_source_permanently(client, user.id, source_id, background_tasks)
    return Response(status_code=204)