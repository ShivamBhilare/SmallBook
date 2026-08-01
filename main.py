from dotenv import load_dotenv
# 1. Load the variables FIRST
load_dotenv() 

from fastapi import FastAPI, Depends, Request, status
from fastapi.responses import RedirectResponse
from app.routers.auth import router as auth_router
from app.routers.notebooks import router as notebooks_router
from app.services.authentication.auth_service import get_optional_current_user

app = FastAPI(title="SmallBook")

# Include the separated routers
app.include_router(auth_router)
app.include_router(notebooks_router)

@app.get("/")
async def root(request: Request, user = Depends(get_optional_current_user)):
    """Root endpoint: redirects authenticated users to dashboard, unauthenticated users to sign-in."""
    if user:
        return RedirectResponse(url="/notebooks/dashboard", status_code=status.HTTP_303_SEE_OTHER)
    return RedirectResponse(url="/auth/sign-in", status_code=status.HTTP_303_SEE_OTHER)

