"""Authentication Router Module.

Exposes HTML page renderers for sign-in, sign-up, password reset, and verification flows,
along with JSON API endpoints for user credential validation, registration, session cookie
issuance, and profile introspection via Supabase Auth.
"""

import os
from typing import Optional

from fastapi import APIRouter, Depends, Form, HTTPException, Request, Response, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from supabase import Client

from app.models.auth_models import (
    ForgotPasswordSchema,
    SignInSchema,
    SignUpSchema,
    UpdatePasswordSchema,
)
from app.services.authentication.auth_service import (
    get_optional_current_user,
    get_supabase_client,
    get_token_from_request,
    login_required,
    resend_verification_email,
    send_password_reset,
    sign_in_user,
    sign_out_user,
    sign_up_user,
    update_user_password,
)

# Create an isolated router object for Auth
router = APIRouter(prefix="/auth", tags=["Auth"])

# Setup templates directory location
templates = Jinja2Templates(directory="app/templates")


def _resolve_redirect_base_url(request: Request = None) -> str:
    """Resolves the canonical public base URL for authentication redirect links.

    Prioritizes reverse-proxy headers (x-forwarded-host, x-forwarded-proto),
    ngrok host headers, environment variables, and falls back to request.base_url.
    """
    if request:
        forwarded_host = request.headers.get("x-forwarded-host")
        if forwarded_host:
            forwarded_proto = request.headers.get("x-forwarded-proto", "https")
            return f"{forwarded_proto}://{forwarded_host}".rstrip("/")

        host = request.headers.get("host")
        if host and "ngrok" in host:
            return f"https://{host}".rstrip("/")

        return str(request.base_url).rstrip("/")

    ngrok_domain = os.getenv("NGROK_DOMAIN")
    if ngrok_domain:
        return f"https://{ngrok_domain}".rstrip("/")
    return "http://localhost:8000"


# ==============================================================================
# HTML PAGE RENDERERS & FORM HANDLERS
# ==============================================================================


@router.get("/sign-in", response_class=HTMLResponse)
async def read_sign_in(
    request: Request,
    user=Depends(get_optional_current_user),
    verified: Optional[bool] = None
):
    """Renders the sign-in page or redirects already-authenticated users to dashboard.

    Args:
        request: FastAPI HTTP request instance.
        user: Authenticated user object if active session exists.
        verified: Optional boolean flag indicating email was just verified.

    Returns:
        HTMLResponse rendering sign-in form or HTTP 307 redirect to dashboard.
    """
    if user:
        return Response(status_code=status.HTTP_307_TEMPORARY_REDIRECT, headers={"Location": "/notebooks/dashboard"})
    return templates.TemplateResponse(
        request=request,
        name="sign_in.html",
        context={"title": "Sign In", "verified": verified}
    )


@router.get("/sign-up", response_class=HTMLResponse)
async def read_sign_up(request: Request, user=Depends(get_optional_current_user)):
    """Renders the sign-up registration page or redirects active users to dashboard.

    Args:
        request: FastAPI HTTP request instance.
        user: Authenticated user object if active session exists.

    Returns:
        HTMLResponse rendering registration form or HTTP 307 redirect to dashboard.
    """
    if user:
        return Response(status_code=status.HTTP_307_TEMPORARY_REDIRECT, headers={"Location": "/notebooks/dashboard"})
    return templates.TemplateResponse(
        request=request,
        name="sign_up.html",
        context={"title": "Sign Up"}
    )


@router.get("/forgot-password", response_class=HTMLResponse)
async def read_forgot_password(request: Request):
    """Renders the password reset request page.

    Args:
        request: FastAPI HTTP request instance.

    Returns:
        HTMLResponse rendering forgot password request form.
    """
    return templates.TemplateResponse(
        request=request,
        name="forgot_password.html",
        context={"title": "Forgot Password"}
    )


@router.get("/update-password", response_class=HTMLResponse)
async def read_update_password(request: Request):
    """Renders the password update form following reset token verification.

    Args:
        request: FastAPI HTTP request instance.

    Returns:
        HTMLResponse rendering password reset form.
    """
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
    """Processes form-encoded password reset submissions.

    Validates password confirmation match, resolves access/recovery token from
    form input or cookie header, and invokes Supabase password update routine.

    Args:
        request: FastAPI HTTP request instance.
        password: New desired password from form.
        confirm_password: Confirmation copy of password.
        access_token: Optional recovery token submitted in form payload.
        client: Supabase client instance.

    Returns:
        RedirectResponse to sign-in on success, or TemplateResponse with error message.
    """
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
async def read_verify_email(request: Request, email: Optional[str] = None):
    """Renders the email verification notice page after user registration.

    Args:
        request: FastAPI HTTP request instance.
        email: Optional email address to display in instructions.

    Returns:
        HTMLResponse rendering email verification confirmation view.
    """
    return templates.TemplateResponse(
        request=request,
        name="verify_email.html",
        context={"title": "Verify Email", "email": email or ""}
    )


@router.get("/callback", response_class=HTMLResponse)
@router.get("/confirm", response_class=HTMLResponse)
async def read_auth_callback(
    request: Request,
    code: Optional[str] = None,
    error: Optional[str] = None,
    error_code: Optional[str] = None,
    error_description: Optional[str] = None
):
    """Handles verification and authentication redirect callbacks from Supabase.

    Renders auth_callback.html which extracts tokens from URL hash fragments or
    query parameters, displays verification status, and redirects the user to sign-in.

    Args:
        request: FastAPI HTTP request instance.
        code: Optional authorization code from PKCE flow.
        error: Optional error code returned by Supabase.
        error_code: Optional sub-error code (e.g. otp_expired).
        error_description: Human-readable error description from Supabase.

    Returns:
        HTMLResponse rendering email verification callback view.
    """
    return templates.TemplateResponse(
        request=request,
        name="auth_callback.html",
        context={
            "title": "Email Verified - SmallBook",
            "code": code or "",
            "error": error or "",
            "error_code": error_code or "",
            "error_description": error_description or ""
        }
    )


# ==============================================================================
# JSON API ENDPOINTS
# ==============================================================================


@router.post("/api/sign-in")
async def api_sign_in(data: SignInSchema, response: Response, client: Client = Depends(get_supabase_client)):
    """Authenticates user credentials against Supabase and sets an HTTP-only session cookie.

    Args:
        data: Validated SignInSchema containing email and password.
        response: FastAPI response object for setting session cookie.
        client: Supabase client instance.

    Returns:
        JSON response with redirect URL and access token.

    Raises:
        HTTPException: If credentials are invalid or Supabase authentication fails.
    """
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
async def api_sign_up(
    data: SignUpSchema,
    response: Response,
    request: Request = None,
    client: Client = Depends(get_supabase_client)
):
    """Registers a new user account with Supabase Auth.

    Args:
        data: Validated SignUpSchema containing email, password, and full name.
        response: FastAPI response object for setting session cookie if auto-confirmed.
        request: Optional incoming FastAPI HTTP request for canonical redirect resolution.
        client: Supabase client instance.

    Returns:
        JSON payload indicating whether an immediate session was established or
        email verification is required.

    Raises:
        HTTPException: If user registration fails in Supabase.
    """
    try:
        redirect_url = f"{_resolve_redirect_base_url(request)}/auth/callback" if request else None
        auth_res = sign_up_user(
            client=client,
            email=data.email,
            password=data.password,
            full_name=data.fullname,
            redirect_to=redirect_url
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
    """Signs out the user, invalidates active session, and deletes the access_token cookie.

    Args:
        request: FastAPI HTTP request containing session cookie.
        response: FastAPI response object to delete cookie.
        client: Supabase client instance.

    Returns:
        JSON payload indicating successful logout.
    """
    token = get_token_from_request(request)
    if token:
        sign_out_user(client, token)
    response.delete_cookie("access_token")
    return {"status": "success", "message": "Signed out successfully."}


@router.post("/api/forgot-password")
async def api_forgot_password(
    request: Request,
    data: ForgotPasswordSchema,
    client: Client = Depends(get_supabase_client)
):
    """Triggers password reset email delivery via Supabase Auth.

    Args:
        request: FastAPI HTTP request instance.
        data: Validated ForgotPasswordSchema containing target email.
        client: Supabase client instance.

    Returns:
        JSON acknowledgement message.

    Raises:
        HTTPException: If reset request fails.
    """
    try:
        redirect_url = f"{_resolve_redirect_base_url(request)}/auth/update-password"
        send_password_reset(client=client, email=data.email, redirect_to=redirect_url)
        return {
            "status": "success",
            "message": "If an account exists with that email, a password reset link has been sent."
        }
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/api/resend-verification")
async def api_resend_verification(
    data: ForgotPasswordSchema,
    request: Request = None,
    client: Client = Depends(get_supabase_client)
):
    """Resends email confirmation link to unverified users.

    Args:
        data: Validated ForgotPasswordSchema containing recipient email.
        request: Optional incoming FastAPI HTTP request for canonical redirect resolution.
        client: Supabase client instance.

    Returns:
        JSON acknowledgement message.

    Raises:
        HTTPException: If email is missing or resend request fails.
    """
    try:
        if not data.email:
            raise HTTPException(status_code=400, detail="Email is required.")
        redirect_url = f"{_resolve_redirect_base_url(request)}/auth/callback" if request else None
        resend_verification_email(client=client, email=data.email, redirect_to=redirect_url)
        return {
            "status": "success",
            "message": "Verification link has been resent. Please check your inbox."
        }
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/api/update-password")
async def api_update_password(data: UpdatePasswordSchema, client: Client = Depends(get_supabase_client)):
    """Updates user password using recovery access token via JSON API.

    Args:
        data: Validated UpdatePasswordSchema with access token and new password.
        client: Supabase client instance.

    Returns:
        JSON payload confirming password update and directing to sign-in.

    Raises:
        HTTPException: If password length is insufficient or update fails.
    """
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
async def api_get_me(user=Depends(login_required)):
    """Returns profile metadata for the currently authenticated user session.

    Args:
        user: User profile resolved by login_required dependency.

    Returns:
        Dictionary containing user ID, email, and custom metadata.
    """
    return {
        "id": user.id,
        "email": user.email,
        "user_metadata": user.user_metadata
    }
