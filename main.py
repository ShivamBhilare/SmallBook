from dotenv import load_dotenv
# 1. Load the variables FIRST
load_dotenv() 

from fastapi import FastAPI, Depends, Request, status
from fastapi.responses import RedirectResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from starlette.exceptions import HTTPException as StarletteHTTPException
from app.routers.auth import router as auth_router
from app.routers.notebooks import router as notebooks_router
from app.routers.sources import router as sources_router, global_sources_router
from app.routers.chat import router as chat_router
from app.services.authentication.auth_service import get_optional_current_user

app = FastAPI(title="SmallBook")

templates = Jinja2Templates(directory="app/templates")

# Include the separated routers
app.include_router(auth_router)
app.include_router(notebooks_router)
app.include_router(sources_router)
app.include_router(global_sources_router)
app.include_router(chat_router)

# --- GLOBAL 404 HANDLER ---
@app.exception_handler(StarletteHTTPException)
async def custom_http_exception_handler(request: Request, exc: StarletteHTTPException):
    # If it's a 404, check request type (API vs HTML page)
    if exc.status_code == 404:
        path = request.url.path
        accept_header = request.headers.get("accept", "")
        if path.startswith("/api/") or "/api/" in path or "application/json" in accept_header:
            return JSONResponse(
                status_code=404,
                content={"detail": exc.detail or "Not Found"}
            )
        return templates.TemplateResponse(
            request=request,
            name="404.html",
            context={"title": "404 - Page Not Found"},
            status_code=404
        )
    # For all other HTTP exceptions (401, 500, etc.), return standard JSON
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": exc.detail}
    )

@app.middleware("http")
async def add_no_cache_headers(request: Request, call_next):
    response = await call_next(request)
    # Prevent browsers from caching HTML pages in BFCache
    if "text/html" in response.headers.get("content-type", ""):
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
    return response

@app.get("/")
async def root(request: Request, user = Depends(get_optional_current_user)):
    """Root endpoint: redirects authenticated users to dashboard, unauthenticated users to sign-in."""
    if user:
        return RedirectResponse(url="/notebooks/dashboard", status_code=status.HTTP_303_SEE_OTHER)
    return RedirectResponse(url="/auth/sign-in", status_code=status.HTTP_303_SEE_OTHER)

