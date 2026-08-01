from typing import Optional
from fastapi import APIRouter, Request, Response, Depends, HTTPException, status
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, EmailStr

from app.services.authentication.auth_service import (
    sign_in_user,
    sign_up_user,
    sign_out_user,
    send_password_reset,
    login_required,
    get_optional_current_user,
    get_token_from_request
)

# Create an isolated router object for Auth
router = APIRouter(prefix="/auth", tags=["Auth"])

# Setup templates directory location
templates = Jinja2Templates(directory="app/templates")

# ==========================================
# PYDANTIC SCHEMAS
# ==========================================
class SignInSchema(BaseModel):
    email: EmailStr
    password: str

class SignUpSchema(BaseModel):
    email: EmailStr
    password: str
    fullname: Optional[str] = None

class ForgotPasswordSchema(BaseModel):
    email: EmailStr

# ==========================================
# HTML PAGE RENDERERS
# ==========================================

@router.get("/sign-in", response_class=HTMLResponse)
async def read_sign_in(request: Request, user = Depends(get_optional_current_user)):
    if user:
        return Response(status_code=status.HTTP_307_TEMPORARY_REDIRECT, headers={"Location": "/notebooks/dashboard"})
    return templates.TemplateResponse(
        request=request, 
        name="sign_in.html", 
        context={"title": "Sign In"}
    )

@router.get("/sign-up", response_class=HTMLResponse)
async def read_sign_up(request: Request, user = Depends(get_optional_current_user)):
    if user:
        return Response(status_code=status.HTTP_307_TEMPORARY_REDIRECT, headers={"Location": "/notebooks/dashboard"})
    return templates.TemplateResponse(
        request=request, 
        name="sign_up.html", 
        context={"title": "Sign Up"}
    )

@router.get("/forgot-password", response_class=HTMLResponse)
async def read_forgot_password(request: Request):
    return templates.TemplateResponse(
        request=request, 
        name="forgot_password.html", 
        context={"title": "Forgot Password"}
    )

@router.get("/update-password", response_class=HTMLResponse)
async def read_update_password(request: Request):
    return templates.TemplateResponse(
        request=request, 
        name="update_password.html", 
        context={"title": "Update Password"}
    )

@router.get("/verify-email", response_class=HTMLResponse)
async def read_verify_email(request: Request):
    return templates.TemplateResponse(
        request=request, 
        name="verify_email.html", 
        context={"title": "Verify Email"}
    )

# ==========================================
# JSON API ENDPOINTS
# ==========================================

@router.post("/api/sign-in")
async def api_sign_in(data: SignInSchema, response: Response):
    """Authenticates user credentials against Supabase and sets session cookie."""
    try:
        auth_res = sign_in_user(email=data.email, password=data.password)
        if not auth_res or not auth_res.session:
            raise HTTPException(status_code=400, detail="Invalid email or password.")
        
        token = auth_res.session.access_token
        # Set access_token HTTP cookie
        response.set_cookie(
            key="access_token",
            value=token,
            httponly=True,
            samesite="lax",
            max_age=auth_res.session.expires_in or 86400
        )
        return {
            "status": "success",
            "message": "Logged in successfully.",
            "redirect_url": "/notebooks/dashboard",
            "access_token": token
        }
    except HTTPException as e:
        raise e
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.post("/api/sign-up")
async def api_sign_up(data: SignUpSchema, response: Response):
    """Registers a new user with Supabase Auth."""
    try:
        auth_res = sign_up_user(
            email=data.email, 
            password=data.password, 
            full_name=data.fullname
        )
        
        # Check if immediate session was established (when auto-confirm is enabled)
        if auth_res and auth_res.session:
            token = auth_res.session.access_token
            response.set_cookie(
                key="access_token",
                value=token,
                httponly=True,
                samesite="lax",
                max_age=auth_res.session.expires_in or 86400
            )
            return {
                "status": "success",
                "session": True,
                "message": "Registration successful! Redirecting...",
                "redirect_url": "/notebooks/dashboard"
            }
        
        # Email confirmation required
        return {
            "status": "success",
            "session": False,
            "message": "Account created! Please check your email to confirm your account before logging in."
        }
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.post("/api/sign-out")
async def api_sign_out(request: Request, response: Response):
    """Signs out the user and clears authentication cookie."""
    token = get_token_from_request(request)
    if token:
        sign_out_user(token)
    response.delete_cookie("access_token")
    return {"status": "success", "message": "Signed out successfully."}

@router.post("/api/forgot-password")
async def api_forgot_password(data: ForgotPasswordSchema):
    """Triggers password reset email via Supabase."""
    try:
        send_password_reset(email=data.email)
        return {
            "status": "success",
            "message": "If an account exists with that email, a password reset link has been sent."
        }
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.get("/api/me")
async def api_get_me(user = Depends(login_required)):
    """Returns profile information for the currently authenticated user."""
    return {
        "id": user.id,
        "email": user.email,
        "user_metadata": user.user_metadata
    }
