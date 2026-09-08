import os
from typing import Optional
from fastapi import Depends, HTTPException, status, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from supabase import create_client, Client, ClientOptions
from dotenv import load_dotenv

# Load environment variables from a .env file
load_dotenv()

# 1. Credentials Verification
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY") or os.getenv("SUPABASE_ANON_KEY")

if not SUPABASE_URL or not SUPABASE_KEY:
    raise ValueError("Supabase credentials (SUPABASE_URL and SUPABASE_KEY or SUPABASE_ANON_KEY) are not set in the environment variables.")

# 2. Security scheme definition
security = HTTPBearer(auto_error=False)

def get_token_from_request(request: Request, credentials: Optional[HTTPAuthorizationCredentials] = None) -> Optional[str]:
    """Helper to extract JWT token from Authorization header or HTTP cookie."""
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

# 3. Per-request Supabase client factory dependency
def get_supabase_client(request: Request) -> Client:
    """Creates a fresh client per request, attaching the user's JWT to trigger RLS."""
    # Now this checks BOTH cookies and headers safely!
    token = get_token_from_request(request) 
    
    if token:
        options = ClientOptions(headers={"Authorization": f"Bearer {token}"})
        return create_client(SUPABASE_URL, SUPABASE_KEY, options=options)
        
    return create_client(SUPABASE_URL, SUPABASE_KEY)

def get_service_role_client() -> Client:
    """Creates a Supabase client using the service role key for background admin operations."""
    service_role_key = os.getenv("SUPABASE_SERVICE_ROLE_KEY") or SUPABASE_KEY
    if not SUPABASE_URL or not service_role_key:
        raise ValueError("Supabase URL or Service Role Key is missing.")
    return create_client(SUPABASE_URL, service_role_key)

# 4. Auth Core Service Functions
def sign_up_user(client: Client, email: str, password: str, full_name: Optional[str] = None):
    """Registers a new user with Supabase Auth using per-request client."""
    data = {"full_name": full_name} if full_name else {}
    response = client.auth.sign_up({
        "email": email,
        "password": password,
        "options": {"data": data}
    })
    return response

def sign_in_user(client: Client, email: str, password: str):
    """Authenticates user email and password with Supabase Auth using per-request client."""
    response = client.auth.sign_in_with_password({
        "email": email,
        "password": password
    })
    return response

def sign_out_user(client: Client, access_token: Optional[str] = None):
    """Signs out the user session using per-request client."""
    try:
        if access_token:
            client.auth.sign_out(access_token)
        else:
            client.auth.sign_out()
    except Exception:
        pass

def send_password_reset(client: Client, email: str, redirect_to: Optional[str] = None):
    """Triggers a password reset email via Supabase Auth using per-request client."""
    options = {"redirectTo": redirect_to} if redirect_to else None
    return client.auth.reset_password_for_email(email, options=options)

def resend_verification_email(client: Client, email: str):
    """Resends signup verification email via Supabase Auth using per-request client."""
    return client.auth.resend({"type": "signup", "email": email})

def update_user_password(client: Client, access_token: str, new_password: str, refresh_token: str = ""):
    """Updates user password using recovery/session token on per-request client."""
    user_response = client.auth.get_user(access_token)
    if not user_response or not user_response.user:
        raise ValueError("Invalid user session token")
    
    # Establish session on this per-request client before updating password
    client.auth.set_session(access_token=access_token, refresh_token=refresh_token or "")
    return client.auth.update_user({"password": new_password})

def get_current_user_from_token(client: Client, token: str):
    """Retrieves user object from Supabase JWT token using per-request client."""
    user_response = client.auth.get_user(token)
    if not user_response or not user_response.user:
        raise ValueError("No user found for the provided token.")
    return user_response.user

# 5. FastAPI Security Dependencies
def login_required(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
    client: Client = Depends(get_supabase_client)
):
    """Dependency enforcing authentication via JWT header or access_token cookie."""
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
    """Optional authentication dependency returning user or None without raising 401."""
    token = get_token_from_request(request, credentials)
    if not token:
        return None
    try:
        return get_current_user_from_token(client, token)
    except Exception:
        return None

