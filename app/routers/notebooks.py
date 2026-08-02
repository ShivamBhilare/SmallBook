from typing import List
from fastapi import APIRouter, Request, Response, Depends, HTTPException, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from supabase import Client
from postgrest.exceptions import APIError
from app.services.authentication.auth_service import login_required, get_optional_current_user, get_supabase_client
from app.services.notebooks import notebook_service
from app.services.notebooks.notebook_service import DatabaseError
from app.models.notebook_models import NotebookCreateSchema, NotebookUpdateSchema, NotebookResponseSchema

# Prefix means all routes here start with /notebooks
router = APIRouter(prefix="/notebooks", tags=["Notebooks"])

templates = Jinja2Templates(directory="app/templates")

# HTML PAGE RENDERERS

@router.get("/dashboard", response_class=HTMLResponse)
async def read_dashboard(request: Request, user=Depends(get_optional_current_user)):
    """Renders the home_page.html after a user logs in."""
    if not user:
        return RedirectResponse(url="/auth/sign-in", status_code=status.HTTP_303_SEE_OTHER)
    return templates.TemplateResponse(
        request=request, 
        name="home_page.html", 
        context={
            "title": "My Notebooks Dashboard",
            "user": user
        }
    )

@router.get("/workspace/{notebook_id}", response_class=HTMLResponse)
async def read_workspace(request: Request, notebook_id: str, user=Depends(get_optional_current_user)):
    if not user:
        return RedirectResponse(url="/auth/sign-in", status_code=status.HTTP_303_SEE_OTHER)
        
    try:
        # Pass 'request' to automatically trigger RLS policy
        response = get_supabase_client(request).table("notebooks").select("id").eq("id", notebook_id).execute()
    except APIError:
        raise HTTPException(status_code=404, detail="Notebook not found")
    
    # RLS ensures this is empty if they don't own the notebook
    if not response.data:
        raise HTTPException(status_code=404, detail="Notebook not found")

    return templates.TemplateResponse(
        request=request, 
        name="notebook_workspace.html", 
        context={
            "title": "Notebook Workspace",
            "notebook_id": notebook_id,
            "user": user
        }
    )

# SECURE API DATA ENDPOINTS

@router.get("/api/list", response_model=dict)
def api_get_notebooks(user=Depends(login_required), client: Client = Depends(get_supabase_client)):
    """API endpoint for the frontend to fetch the user's notebooks."""
    try:
        notebooks = notebook_service.get_user_notebooks(client, user.id)
        return {"notebooks": notebooks}
    except DatabaseError as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))

@router.get("/api/{notebook_id}", response_model=dict)
def api_get_single_notebook(notebook_id: str, user=Depends(login_required), client: Client = Depends(get_supabase_client)):
    """API endpoint to load specific notebook data into the workspace."""
    try:
        notebook = notebook_service.get_notebook_by_id(client, notebook_id, user.id)
        if not notebook:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Notebook not found or you don't have access."
            )
        return {"notebook": notebook}
    except DatabaseError as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))

@router.post("/api/create", response_model=dict, status_code=status.HTTP_201_CREATED)
def api_create_notebook(
    payload: NotebookCreateSchema, 
    user=Depends(login_required), 
    client: Client = Depends(get_supabase_client)
):
    """API endpoint to create a new notebook."""
    try:
        notebook = notebook_service.create_notebook(client, user.id, payload)
        return {"notebook": notebook}
    except DatabaseError as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))

@router.patch("/api/{notebook_id}", response_model=dict)
def api_update_notebook(
    notebook_id: str, 
    payload: NotebookUpdateSchema, 
    user=Depends(login_required), 
    client: Client = Depends(get_supabase_client)
):
    """API endpoint to update an existing notebook."""
    try:
        notebook = notebook_service.update_notebook(client, notebook_id, user.id, payload)
        if not notebook:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Notebook not found or you don't have access."
            )
        return {"notebook": notebook}
    except DatabaseError as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))

@router.delete("/api/{notebook_id}", status_code=status.HTTP_204_NO_CONTENT)
def api_delete_notebook(
    notebook_id: str, 
    user=Depends(login_required), 
    client: Client = Depends(get_supabase_client)
):
    """API endpoint to delete a notebook."""
    try:
        success = notebook_service.delete_notebook(client, notebook_id, user.id)
        if not success:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Notebook not found or you don't have access."
            )
        return Response(status_code=status.HTTP_204_NO_CONTENT)
    except DatabaseError as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))