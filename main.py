"""SmallBook Application Entrypoint.

Bootstraps the FastAPI application, mounts static assets and Jinja2 templates,
configures no-cache HTTP middlewares, registers modular API routers, and defines
global error handlers and landing page endpoints.
"""

from dotenv import load_dotenv

# 1. Load environment variables before any internal package imports execute
load_dotenv()

from fastapi import Depends, FastAPI, Request, status
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.exceptions import HTTPException as StarletteHTTPException

import app.core.celery_app  # Initialize Celery app and broker configuration
from app.routers.auth import router as auth_router
from app.routers.chat import router as chat_router
from app.routers.dev_emails import router as dev_emails_router
from app.routers.llm_settings import router as llm_settings_router
from app.routers.notebooks import router as notebooks_router
from app.routers.sources import global_sources_router, router as sources_router
from app.routers.study import router as study_router
from app.services.authentication.auth_service import get_optional_current_user

# ==============================================================================
# FASTAPI APPLICATION INSTANTIATION & STATIC CONFIGURATION
# ==============================================================================

app = FastAPI(title="SmallBook")


@app.middleware("http")
async def add_no_cache_headers_for_static(request: Request, call_next):
    """Middleware ensuring static files are never aggressively cached in local development.

    Args:
        request: Incoming HTTP request.
        call_next: Next request processing middleware or endpoint handler.

    Returns:
        HTTP Response with explicit no-cache headers attached for static resources.
    """
    response = await call_next(request)
    if request.url.path.startswith("/static/"):
        response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate, max-age=0"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
    return response


# Mount static asset directory for CSS stylesheets, JavaScript modules, and images
app.mount("/static", StaticFiles(directory="app/static"), name="static")

# Jinja2 template rendering engine initialization
templates = Jinja2Templates(directory="app/templates")

# ==============================================================================
# ROUTER REGISTRATION
# ==============================================================================

# Include separated domain routers
app.include_router(auth_router)
app.include_router(notebooks_router)
app.include_router(sources_router)
app.include_router(global_sources_router)
app.include_router(chat_router)
app.include_router(llm_settings_router)
app.include_router(study_router)
app.include_router(dev_emails_router)

# ==============================================================================
# GLOBAL EXCEPTION HANDLERS & HTTP MIDDLEWARE
# ==============================================================================


@app.exception_handler(StarletteHTTPException)
async def custom_http_exception_handler(request: Request, exc: StarletteHTTPException):
    """Global HTTP exception handler routing 404s and server errors.

    Differentiates between API requests (expecting JSON responses) and browser
    navigation requests (rendering user-friendly 404 HTML template).

    Args:
        request: The incoming Starlette/FastAPI request.
        exc: Caught HTTP exception instance.

    Returns:
        JSONResponse or TemplateResponse depending on client Accept header and path.
    """
    # If it's a 404, check request type (API vs HTML page)
    if exc.status_code == 404:
        path = request.url.path
        accept_header = request.headers.get("accept", "")
        if (
            path.startswith("/api/")
            or "/api/" in path
            or "application/json" in accept_header
            or request.method in ("POST", "PUT", "PATCH", "DELETE")
        ):
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
    """Middleware preventing browsers from caching HTML pages in Back-Forward Cache (BFCache).

    Guarantees user session state and authentication tokens are accurately checked
    on every page transition.

    Args:
        request: Incoming HTTP request.
        call_next: Downstream handler pipeline.

    Returns:
        HTTP response with headers set to forbid HTML caching.
    """
    response = await call_next(request)
    # Prevent browsers from caching HTML pages in BFCache
    if "text/html" in response.headers.get("content-type", ""):
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
    return response


# ==============================================================================
# HEALTHCHECK ENDPOINT (Used by Docker, load balancers, and monitoring)
# ==============================================================================


@app.get("/health")
async def health_check():
    """Healthcheck endpoint verifying the FastAPI service is active and responsive."""
    return {"status": "ok", "service": "smallbook"}


# ==============================================================================
# ROOT & LANDING PAGE ENDPOINTS
# ==============================================================================


@app.get("/", response_class=HTMLResponse)
async def root(request: Request, user=Depends(get_optional_current_user)):
    """Renders the public landing page with options to sign up, sign in, or go to dashboard.

    Args:
        request: FastAPI HTTP request instance.
        user: Optional authenticated user object if session cookie is valid.

    Returns:
        HTMLResponse rendering the landing page template.
    """
    return templates.TemplateResponse(
        request=request,
        name="landing.html",
        context={
            "request": request,
            "user": user,
            "title": "SmallBook - Grounded AI Research & Study Workspace"
        }
    )


@app.get("/landing", response_class=HTMLResponse)
async def landing(request: Request, user=Depends(get_optional_current_user)):
    """Direct alias endpoint for the SmallBook landing page.

    Args:
        request: FastAPI HTTP request instance.
        user: Optional authenticated user object if session cookie is valid.

    Returns:
        HTMLResponse rendering the landing page template.
    """
    return templates.TemplateResponse(
        request=request,
        name="landing.html",
        context={
            "request": request,
            "user": user,
            "title": "SmallBook - Grounded AI Research & Study Workspace"
        }
    )
