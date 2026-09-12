"""
Supabase Authentication & Identity Service

Coordinates user registration, session authentication, password management, and
JWT verification interfacing with Supabase GoTrue. Provides per-request Supabase
client factories that propagate JWT bearer tokens to enforce PostgreSQL Row-Level
Security (RLS) policies on downstream database queries.
"""

import os
from typing import Optional
from fastapi import Depends, HTTPException, status, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from supabase import create_client, Client, ClientOptions
from dotenv import load_dotenv

load_dotenv()

# Supabase API endpoint URL and anonymous public API key verification
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY") or os.getenv("SUPABASE_ANON_KEY")

if not SUPABASE_URL or not SUPABASE_KEY:
    raise ValueError("Supabase credentials (SUPABASE_URL and SUPABASE_KEY or SUPABASE_ANON_KEY) are not set in the environment variables.")

# FastAPI HTTPBearer security scheme (auto_error=False permits fallback to HTTP cookies)
security = HTTPBearer(auto_error=False)


# =========================================================================
# 1. TOKEN EXTRACTION & CLIENT FACTORIES
# =========================================================================

def get_token_from_request(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = None
) -> Optional[str]:
    """
    Extracts a JWT authentication token from the incoming HTTP request.

    Checks credentials in descending order of precedence:
    1. Authorization header parsed via FastAPI HTTPBearer (`credentials.credentials`).
    2. Raw `Authorization: Bearer <token>` HTTP header.
    3. `access_token` HTTP cookie (supporting server-rendered HTML views).

    Args:
        request: The incoming FastAPI HTTP request.
        credentials: Optional credentials parsed by FastAPI security scheme.

    Returns:
        Optional[str]: Extracted raw JWT string, or None if no token is present.
    """
    if credentials and credentials.credentials:
        return credentials.credentials
    auth_header = request.headers.get("Authorization")
    if auth_header and auth_header.startswith("Bearer "):
        return auth_header[7:]
    token = request.cookies.get("access_token")
    if token:
        if token.startswith("Bearer "):
            return token[7:]
        return token
    return None


def get_supabase_client(request: Request) -> Client:
    """
    Creates a per-request Supabase client instance with RLS context.

    If an authentication token is resolved from the request (headers or cookies),
    attaches an `Authorization: Bearer <token>` header to all outgoing requests from
    this client instance. This ensures Supabase evaluates Row-Level Security (RLS)
    policies using the authenticating user's identity.

    Args:
        request: The active FastAPI HTTP request.

    Returns:
        Client: An initialized Supabase client scoped to the requesting user.
    """
    token = get_token_from_request(request)
    
    if token:
        options = ClientOptions(headers={"Authorization": f"Bearer {token}"})
        return create_client(SUPABASE_URL, SUPABASE_KEY, options=options)
        
    return create_client(SUPABASE_URL, SUPABASE_KEY)


def get_service_role_client() -> Client:
    """
    Creates a privileged Supabase client using the service role secret.

    Bypasses Row-Level Security (RLS) for internal administrative background jobs,
    asynchronous Celery workers, and system bootstrap maintenance.

    Returns:
        Client: Elevated Supabase client instance.

    Raises:
        ValueError: If SUPABASE_URL or the service role key is missing from environment.
    """
    service_role_key = os.getenv("SUPABASE_SERVICE_ROLE_KEY") or SUPABASE_KEY
    if not SUPABASE_URL or not service_role_key:
        raise ValueError("Supabase URL or Service Role Key is missing.")
    return create_client(SUPABASE_URL, service_role_key)


# =========================================================================
# 2. AUTHENTICATION CORE ACTIONS
# =========================================================================

def sign_up_user(client: Client, email: str, password: str, full_name: Optional[str] = None):
    """
    Registers a new user account with Supabase Auth (GoTrue).

    Args:
        client: The per-request Supabase client.
        email: New user's email address.
        password: Plaintext password meeting security criteria.
        full_name: Optional user display name stored in user_metadata.

    Returns:
        AuthResponse: Supabase authentication response containing user object and session.
    """
    data = {"full_name": full_name} if full_name else {}
    response = client.auth.sign_up({
        "email": email,
        "password": password,
        "options": {"data": data}
    })
    return response


def sign_in_user(client: Client, email: str, password: str):
    """
    Authenticates a user using email and password credentials.

    Args:
        client: The per-request Supabase client.
        email: Registered account email.
        password: Plaintext account password.

    Returns:
        AuthResponse: Supabase authentication response with JWT access and refresh tokens.
    """
    response = client.auth.sign_in_with_password({
        "email": email,
        "password": password
    })
    return response


def sign_out_user(client: Client, access_token: Optional[str] = None):
    """
    Invalidates the active user session in Supabase Auth.

    Args:
        client: The per-request Supabase client.
        access_token: Optional specific access token to revoke.
    """
    try:
        if access_token:
            client.auth.sign_out(access_token)
        else:
            client.auth.sign_out()
    except Exception:
        pass


def send_password_reset(client: Client, email: str, redirect_to: Optional[str] = None):
    """
    Triggers a password recovery email containing a magic reset link.

    Args:
        client: The per-request Supabase client.
        email: The target user account email.
        redirect_to: Optional redirect URL after the user clicks the reset link.

    Returns:
        Any: Supabase auth dispatch confirmation.
    """
    options = {"redirectTo": redirect_to} if redirect_to else None
    return client.auth.reset_password_for_email(email, options=options)


def resend_verification_email(client: Client, email: str):
    """
    Resends the initial account confirmation / email verification link.

    Args:
        client: The per-request Supabase client.
        email: The target user account email.

    Returns:
        Any: Supabase auth resend confirmation.
    """
    return client.auth.resend({"type": "signup", "email": email})


def update_user_password(
    client: Client,
    access_token: str,
    new_password: str,
    refresh_token: str = ""
):
    """
    Updates the authenticated user's account password.

    Establishes the session on the per-request client using the recovery token
    prior to issuing the password update command.

    Args:
        client: The per-request Supabase client.
        access_token: Temporary password recovery or active session access token.
        new_password: The new plaintext password.
        refresh_token: Optional accompanying refresh token string.

    Returns:
        UserResponse: Updated user representation from Supabase.

    Raises:
        ValueError: If the provided session token is invalid or expired.
    """
    user_response = client.auth.get_user(access_token)
    if not user_response or not user_response.user:
        raise ValueError("Invalid user session token")
    
    # Establish session on this per-request client before updating password
    client.auth.set_session(access_token=access_token, refresh_token=refresh_token or "")
    return client.auth.update_user({"password": new_password})


def get_current_user_from_token(client: Client, token: str):
    """
    Resolves and verifies a user profile entity from a JWT token string.

    Args:
        client: The per-request Supabase client.
        token: Raw JWT bearer token string.

    Returns:
        User: Supabase User object.

    Raises:
        ValueError: If token validation fails or no user is associated with the token.
    """
    user_response = client.auth.get_user(token)
    if not user_response or not user_response.user:
        raise ValueError("No user found for the provided token.")
    return user_response.user


# =========================================================================
# 3. FASTAPI SECURITY DEPENDENCIES
# =========================================================================

def login_required(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
    client: Client = Depends(get_supabase_client)
):
    """
    FastAPI dependency enforcing mandatory user authentication.

    Resolves the authentication token from request headers or session cookies.
    If absent or invalid, immediately halts request processing with an HTTP 401.

    Args:
        request: The active FastAPI HTTP request.
        credentials: Optional credentials parsed via HTTPBearer.
        client: Per-request Supabase client.

    Returns:
        User: Authenticated Supabase User object.

    Raises:
        HTTPException: 401 Unauthorized if token is missing, expired, or invalid.
    """
    token = get_token_from_request(request, credentials)
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication token missing",
        )
    try:
        return get_current_user_from_token(client, token)
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
        )


def get_optional_current_user(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
    client: Client = Depends(get_supabase_client)
):
    """
    FastAPI dependency resolving optional user authentication.

    Used on public endpoints (e.g. landing page or marketing views) that adapt their
    UI layout if a user is logged in, but allow anonymous browsing without raising 401.

    Args:
        request: The active FastAPI HTTP request.
        credentials: Optional credentials parsed via HTTPBearer.
        client: Per-request Supabase client.

    Returns:
        Optional[User]: Authenticated Supabase User object, or None if unauthenticated.
    """
    token = get_token_from_request(request, credentials)
    if not token:
        return None
    try:
        return get_current_user_from_token(client, token)
    except Exception:
        return None


# =========================================================================
# 5. PUBLIC ASSETS & STORAGE HELPERS
# =========================================================================

SUPABASE_PUBLIC_LOGO_URL = (
    f"{SUPABASE_URL}/storage/v1/object/public/assets/SmallBooklogo.png"
    if SUPABASE_URL
    else "https://vizwxdshoovaupmdccuu.supabase.co/storage/v1/object/public/assets/SmallBooklogo.png"
)


def ensure_supabase_public_logo() -> str:
    """
    Ensures that the public 'assets' bucket exists in Supabase Storage and that
    SmallBooklogo.png is uploaded and publicly accessible for transactional emails.

    Returns:
        str: Permanent HTTPS public URL to SmallBooklogo.png.
    """
    logo_filename = "SmallBooklogo.png"
    fallback_url = SUPABASE_PUBLIC_LOGO_URL
    try:
        service_client = get_service_role_client()
        existing_buckets = [b.name for b in service_client.storage.list_buckets()]
        if "assets" not in existing_buckets:
            service_client.storage.create_bucket("assets", options={"public": True})

        logo_path = os.path.join("app", "static", "images", logo_filename)
        if os.path.exists(logo_path):
            with open(logo_path, "rb") as f:
                file_bytes = f.read()
            service_client.storage.from_("assets").upload(
                path=logo_filename,
                file=file_bytes,
                file_options={"content-type": "image/png", "upsert": "true"}
            )
        return service_client.storage.from_("assets").get_public_url(logo_filename)
    except Exception:
        return fallback_url



