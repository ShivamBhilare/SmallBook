import os
from typing import Optional
from fastapi import Depends, HTTPException, status, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from supabase import create_client, Client
from dotenv import load_dotenv

# Load environment variables from a .env file
load_dotenv()

# 1. Initialize Supabase Client
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

if not SUPABASE_URL or not SUPABASE_KEY:
    raise ValueError("Supabase credentials are not set in the environment variables.")

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# 2. Define security scheme (auto_error=False allows falling back to cookies)
security = HTTPBearer(auto_error=False)

# 3. Auth Core Service Functions
def sign_up_user(email: str, password: str, full_name: Optional[str] = None):
    """Registers a new user with Supabase Auth."""
    data = {"full_name": full_name} if full_name else {}
    response = supabase.auth.sign_up({
        "email": email,
        "password": password,
        "options": {"data": data}
    })
    return response

def sign_in_user(email: str, password: str):
    """Authenticates a user using email and password with Supabase Auth."""
    response = supabase.auth.sign_in_with_password({
        "email": email,
        "password": password
    })
    return response

def sign_out_user(access_token: Optional[str] = None):
    """Signs out the current user session."""
    try:
        if access_token:
            supabase.auth.sign_out(access_token)
        else:
            supabase.auth.sign_out()
    except Exception:
        pass

def send_password_reset(email: str, redirect_to: Optional[str] = None):
    """Triggers a password reset email via Supabase Auth."""
    options = {"redirectTo": redirect_to} if redirect_to else None
    return supabase.auth.reset_password_for_email(email, options=options)

def update_user_password(access_token: str, new_password: str):
    """Updates user password using session token."""
    # Set session first or update user
    user_response = supabase.auth.get_user(access_token)
    if not user_response.user:
        raise ValueError("Invalid user session token")
    return supabase.auth.update_user({"password": new_password})

def get_token_from_request(request: Request, credentials: Optional[HTTPAuthorizationCredentials] = None) -> Optional[str]:
    """Helper to extract JWT token from Authorization header or HTTP cookie."""
    if credentials and credentials.credentials:
        return credentials.credentials
    token = request.cookies.get("access_token")
    if token:
        # Strip Bearer prefix if present
        if token.startswith("Bearer "):
            return token[7:]
        return token
    return None

def get_current_user_from_token(token: str):
    """Retrieves user object from Supabase JWT token."""
    user_response = supabase.auth.get_user(token)
    if not user_response or not user_response.user:
        raise ValueError("No user found for the provided token.")
    return user_response.user

# 4. FastAPI Security Dependencies
def login_required(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security)
):
    """Dependency enforcing authentication via JWT header or access_token cookie."""
    token = get_token_from_request(request, credentials)
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication token missing",
        )
    try:
        return get_current_user_from_token(token)
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
        )

def get_optional_current_user(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security)
):
    """Optional authentication dependency that returns user or None without raising 401."""
    token = get_token_from_request(request, credentials)
    if not token:
        return None
    try:
        return get_current_user_from_token(token)
    except Exception:
        return None