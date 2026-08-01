from typing import Optional
from fastapi import APIRouter, Request, Response, Depends, HTTPException, status, Form
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, EmailStr
from supabase import Client

from app.services.authentication.auth_service import (
    sign_in_user,
    sign_up_user,
    sign_out_user,
    send_password_reset,
    update_user_password,
    login_required,
    get_optional_current_user,
    get_token_from_request,
    get_supabase_client
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

class UpdatePasswordSchema(BaseModel):
    access_token: str
    password: str
    refresh_token: Optional[str] = ""

# ==========================================
# HTML PAGE RENDERERS & FORM HANDLERS
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

@router.post("/update-password")
async def post_update_password(
    request: Request,
    password: str = Form(...),
    confirm_password: str = Form(...),
    access_token: Optional[str] = Form(None),
    client: Client = Depends(get_supabase_client)
):
    """POST handler alongside read_update_password processing form-encoded password reset input."""
    if password != confirm_password:
        return templates.TemplateResponse(
            request=request,
            name="update_password.html",
            context={"title": "Update Password", "error_msg": "Passwords do not match."}
        )
    
    token = access_token or get_token_from_request(request)
    if not token:
        return templates.TemplateResponse(
            request=request,
            name="update_password.html",
            context={"title": "Update Password", "error_msg": "Recovery token missing or expired. Please request a new password reset."}
        )
        
    try:
        update_user_password(client=client, access_token=token, new_password=password)
        return RedirectResponse(url="/auth/sign-in", status_code=status.HTTP_303_SEE_OTHER)
    except Exception as e:
        return templates.TemplateResponse(
            request=request,
            name="update_password.html",
            context={"title": "Update Password", "error_msg": str(e)}
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
async def api_sign_in(data: SignInSchema, response: Response, client: Client = Depends(get_supabase_client)):
    """Authenticates user credentials against Supabase and sets session cookie."""
    try:
        auth_res = sign_in_user(client=client, email=data.email, password=data.password)
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
async def api_sign_up(data: SignUpSchema, response: Response, client: Client = Depends(get_supabase_client)):
    """Registers a new user with Supabase Auth."""
    try:
        auth_res = sign_up_user(
            client=client,
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
async def api_sign_out(request: Request, response: Response, client: Client = Depends(get_supabase_client)):
    """Signs out the user and clears authentication cookie."""
    token = get_token_from_request(request)
    if token:
        sign_out_user(client, token)
    response.delete_cookie("access_token")
    return {"status": "success", "message": "Signed out successfully."}

@router.post("/api/forgot-password")
async def api_forgot_password(data: ForgotPasswordSchema, client: Client = Depends(get_supabase_client)):
    """Triggers password reset email via Supabase."""
    try:
        send_password_reset(client=client, email=data.email)
        return {
            "status": "success",
            "message": "If an account exists with that email, a password reset link has been sent."
        }
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.post("/api/update-password")
async def api_update_password(data: UpdatePasswordSchema, client: Client = Depends(get_supabase_client)):
    """Updates user password using the recovery / access token."""
    try:
        if not data.password or len(data.password) < 6:
            raise HTTPException(status_code=400, detail="Password must be at least 6 characters.")
        update_user_password(
            client=client,
            access_token=data.access_token,
            new_password=data.password,
            refresh_token=data.refresh_token or ""
        )
        return {
            "status": "success",
            "message": "Password updated successfully. You can now sign in with your new password.",
            "redirect_url": "/auth/sign-in"
        }
    except HTTPException as e:
        raise e
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

