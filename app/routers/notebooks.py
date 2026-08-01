from fastapi import APIRouter, Request, Response, Depends, HTTPException, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from app.services.authentication.auth_service import login_required, get_optional_current_user
from app.services.notebooks import notebook_service

# Prefix means all routes here start with /notebooks
router = APIRouter(prefix="/notebooks", tags=["Notebooks"])

templates = Jinja2Templates(directory="app/templates")

# ==========================================
# HTML PAGE RENDERERS
# ==========================================

@router.get("/dashboard", response_class=HTMLResponse)
async def read_dashboard(request: Request, user = Depends(get_optional_current_user)):
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
async def read_workspace(request: Request, notebook_id: str, user = Depends(get_optional_current_user)):
    """Renders the notebook_workspace.html for a specific notebook."""
    if not user:
        return RedirectResponse(url="/auth/sign-in", status_code=status.HTTP_303_SEE_OTHER)
    return templates.TemplateResponse(
        request=request, 
        name="notebook_workspace.html", 
        context={
            "title": "Notebook Workspace",
            "notebook_id": notebook_id,
            "user": user
        }
    )

# ==========================================
# SECURE API DATA ENDPOINTS
# ==========================================

@router.get("/api/list")
def api_get_notebooks(user = Depends(login_required)):
    """API endpoint for the frontend to fetch the user's notebooks."""
    notebooks = notebook_service.get_user_notebooks(user.id)
    return {"notebooks": notebooks}

@router.get("/api/{notebook_id}")
def api_get_single_notebook(notebook_id: str, user = Depends(login_required)):
    """API endpoint to load specific notebook data into the workspace."""
    notebook = notebook_service.get_notebook_by_id(notebook_id, user.id)
    
    if not notebook:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Notebook not found or you don't have access."
        )
        
    return {"notebook": notebook}