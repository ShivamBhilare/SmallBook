"""Notebook Workspaces Router Module.

Exposes HTML page renderers for the user dashboard and individual notebook
workspaces, along with RESTful JSON API endpoints for creating, retrieving,
updating, and deleting notebooks under row-level security controls.
"""

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from postgrest.exceptions import APIError
from supabase import Client

from app.models.notebook_models import NotebookCreateSchema, NotebookUpdateSchema
from app.services.authentication.auth_service import (
    get_optional_current_user,
    get_supabase_client,
    login_required,
)
from app.services.notebooks import notebook_service
from app.services.notebooks.notebook_service import DatabaseError

# Prefix means all routes here start with /notebooks
router = APIRouter(prefix="/notebooks", tags=["Notebooks"])

templates = Jinja2Templates(directory="app/templates")

# ==============================================================================
# HTML PAGE RENDERERS
# ==============================================================================


@router.get("/dashboard", response_class=HTMLResponse)
async def read_dashboard(request: Request, user=Depends(get_optional_current_user)):
    """Renders the dashboard home page listing user notebooks.

    Redirects unauthenticated visitors to the sign-in page.

    Args:
        request: FastAPI HTTP request instance.
        user: Authenticated user object if active session exists.

    Returns:
        HTMLResponse rendering home_page.html template or HTTP 303 redirect.
    """
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
    """Renders the full tri-pane notebook workspace UI.

    Validates notebook existence and ownership, loads linked sources, and initializes
    the interactive workspace shell.

    Args:
        request: FastAPI HTTP request instance.
        notebook_id: UUID of the workspace notebook.
        user: Authenticated user object.

    Returns:
        HTMLResponse rendering notebook_workspace.html.

    Raises:
        HTTPException: 404 if notebook not found or unauthorized.
    """
    if not user:
        return RedirectResponse(url="/auth/sign-in", status_code=status.HTTP_303_SEE_OTHER)

    client = get_supabase_client(request)
    try:
        # Pass 'request' to automatically trigger RLS policy, and explicitly filter user_id for defense in depth
        response = client.table("notebooks").select("id, title").eq("id", notebook_id).eq("user_id", user.id).execute()
    except APIError:
        raise HTTPException(status_code=404, detail="Notebook not found")

    # RLS ensures this is empty if they don't own the notebook
    if not response.data:
        raise HTTPException(status_code=404, detail="Notebook not found")

    notebook_data = response.data[0]

    from app.services.sources.source_service import get_notebook_sources
    sources = get_notebook_sources(client, notebook_id)

    return templates.TemplateResponse(
        request=request,
        name="notebook_workspace.html",
        context={
            "title": "Notebook Workspace",
            "notebook_id": notebook_id,
            "user": user,
            "notebook": notebook_data,
            "sources": sources
        }
    )


# ==============================================================================
# SECURE API DATA ENDPOINTS
# ==============================================================================


@router.get("/api/list", response_model=dict)
def api_get_notebooks(user=Depends(login_required), client: Client = Depends(get_supabase_client)):
    """Fetches all notebooks owned by the authenticated user with attached source counts.

    Args:
        user: Authenticated user object from dependency.
        client: Supabase client instance.

    Returns:
        Dictionary containing 'notebooks' list.

    Raises:
        HTTPException: 500 if database query fails.
    """
    try:
        notebooks = notebook_service.get_user_notebooks(client, user.id)
        return {"notebooks": notebooks}
    except DatabaseError as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))


@router.get("/api/{notebook_id}", response_model=dict)
def api_get_single_notebook(notebook_id: str, user=Depends(login_required), client: Client = Depends(get_supabase_client)):
    """Loads specific notebook metadata by UUID.

    Args:
        notebook_id: UUID of the notebook.
        user: Authenticated user object from dependency.
        client: Supabase client instance.

    Returns:
        Dictionary containing 'notebook' object.

    Raises:
        HTTPException: 404 if not found or unauthorized; 500 on database error.
    """
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
    """Creates a new notebook workspace for the authenticated user.

    Args:
        payload: NotebookCreateSchema with title and optional description.
        user: Authenticated user object from dependency.
        client: Supabase client instance.

    Returns:
        Dictionary containing created 'notebook' record.

    Raises:
        HTTPException: 500 on database error.
    """
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
    """Updates title or description of an existing notebook workspace.

    Args:
        notebook_id: UUID of the notebook to update.
        payload: NotebookUpdateSchema with optional title/description updates.
        user: Authenticated user object from dependency.
        client: Supabase client instance.

    Returns:
        Dictionary containing updated 'notebook' record.

    Raises:
        HTTPException: 404 if not found; 500 on database error.
    """
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
    """Deletes a notebook workspace and triggers cascading deletion of links and chats.

    Args:
        notebook_id: UUID of the notebook to delete.
        user: Authenticated user object from dependency.
        client: Supabase client instance.

    Returns:
        HTTP 204 No Content Response.

    Raises:
        HTTPException: 404 if not found; 500 on database error.
    """
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