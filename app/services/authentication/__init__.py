"""
Authentication Service Package

Exports authentication helpers, client factories, and FastAPI dependencies
interfacing with Supabase GoTrue authentication services.
"""

from app.services.authentication.auth_service import (
    get_token_from_request,
    get_supabase_client,
    get_service_role_client,
    sign_up_user,
    sign_in_user,
    sign_out_user,
    send_password_reset,
    resend_verification_email,
    update_user_password,
    get_current_user_from_token,
    login_required,
    get_optional_current_user,
)

__all__ = [
    "get_token_from_request",
    "get_supabase_client",
    "get_service_role_client",
    "sign_up_user",
    "sign_in_user",
    "sign_out_user",
    "send_password_reset",
    "resend_verification_email",
    "update_user_password",
    "get_current_user_from_token",
    "login_required",
    "get_optional_current_user",
]

