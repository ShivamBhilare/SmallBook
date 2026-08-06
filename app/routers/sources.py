from fastapi import APIRouter, Depends, UploadFile, File, BackgroundTasks, HTTPException, Response
from supabase import Client
from app.services.authentication.auth_service import login_required, get_supabase_client
from app.services.sources import source_service
from app.models.source_models import SourceUploadResponse, SourceRenameSchema

router = APIRouter(prefix="/notebooks/{notebook_id}/sources", tags=["Sources"])

@router.post("/upload", response_model=SourceUploadResponse, status_code=202)
async def upload_source(
    notebook_id: str,
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    user = Depends(login_required),
    client: Client = Depends(get_supabase_client)
):
    """
    Endpoint to upload a PDF source to a specific notebook.
    Verifies auth, checks for duplicates, pushes to Supabase Storage in background, and triggers Celery.
    """
    # 1. RLS verifies notebook ownership implicitly during DB insertion, but we can double check here
    # to prevent people uploading to notebooks they don't own.
    notebook_check = client.table("notebooks").select("id").eq("id", notebook_id).execute()
    if not notebook_check.data:
        raise HTTPException(status_code=404, detail="Notebook not found or access denied.")

    # 2. Handoff to service layer
    result = source_service.handle_source_upload(
        client=client, 
        user_id=user.id, 
        notebook_id=notebook_id, 
        file=file,
        background_tasks=background_tasks
    )
    
    return result

@router.patch("/{source_id}/rename", response_model=dict)
def rename_source(
    notebook_id: str,
    source_id: str,
    payload: SourceRenameSchema,
    user = Depends(login_required),
    client: Client = Depends(get_supabase_client)
):
    """
    Renames a source document.
    """
    updated_source = source_service.rename_source(client, user.id, source_id, payload.filename)
    return {"status": "success", "source": updated_source}

@router.delete("/{source_id}", status_code=204)
def remove_source(
    notebook_id: str,
    source_id: str,
    mode: str = "notebook",
    user = Depends(login_required),
    client: Client = Depends(get_supabase_client)
):
    """
    Removes a source document.
    mode='notebook': Unlinks source from this notebook.
    mode='library': Permanently deletes source from everywhere (storage bucket + DB).
    """
    if mode == "library":
        source_service.delete_source_permanently(client, user.id, source_id)
    else:
        source_service.remove_source_from_notebook(client, user.id, notebook_id, source_id)
    return Response(status_code=204)