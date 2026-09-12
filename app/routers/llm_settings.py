"""LLM Settings & BYOK API Router Module.

Exposes RESTful endpoints for managing Bring-Your-Own-Key (BYOK) provider credentials,
running live dry-run key verifications, configuring user model preferences, and
checking free-tier usage and burst rate limits.
"""

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from supabase import Client

from app.services.authentication.auth_service import get_supabase_client, login_required
from app.services.llm.free_tier import get_free_tier_status
from app.services.llm.key_service import (
    DEFAULT_PREFERRED_MODELS,
    PROVIDER_CATALOG,
    delete_user_credential,
    get_user_credentials,
    get_user_preferences,
    save_user_credential,
    save_user_preferences,
    validate_provider_key,
)

router = APIRouter(prefix="/api/llm", tags=["LLM Settings & BYOK"])


class SaveKeySchema(BaseModel):
    """Payload schema for storing or updating an encrypted BYOK API key."""
    provider: str
    raw_key: str
    api_base: Optional[str] = None
    custom_model_name: Optional[str] = None


class VerifyKeySchema(BaseModel):
    """Payload schema for testing an API key via a live dry-run token request."""
    provider: str
    raw_key: str
    api_base: Optional[str] = None
    model: Optional[str] = None


class SavePreferencesSchema(BaseModel):
    """Payload schema for updating user preferred models and fallback behaviors."""
    active_model: str
    preferred_models: List[Dict[str, Any]]
    fallback_enabled: bool = True


@router.get("/catalog")
def get_provider_catalog(user=Depends(login_required)):
    """Returns the master catalog of supported LLM providers and recommended default models.

    Args:
        user: Authenticated user object from dependency.

    Returns:
        Dictionary containing 'catalog' of providers and 'default_models' list.
    """
    return {
        "catalog": PROVIDER_CATALOG,
        "default_models": DEFAULT_PREFERRED_MODELS
    }


@router.get("/keys")
def list_user_keys(
    user=Depends(login_required),
    client: Client = Depends(get_supabase_client)
):
    """Lists all stored BYOK credentials for the current user in masked format.

    Args:
        user: Authenticated user object from dependency.
        client: Supabase client instance.

    Returns:
        Dictionary containing masked 'credentials' list.
    """
    user_id = user.id if hasattr(user, "id") else user.get("id")
    credentials = get_user_credentials(client, str(user_id))
    return {"credentials": credentials}


@router.post("/keys")
def upsert_user_key(
    payload: SaveKeySchema,
    user=Depends(login_required),
    client: Client = Depends(get_supabase_client)
):
    """Encrypts and stores a user API key using AES-256-GCM.

    Performs an optional dry-run verification against the provider before
    persisting the encrypted ciphertext into the database.

    Args:
        payload: SaveKeySchema with provider, raw_key, optional api_base, and model.
        user: Authenticated user object from dependency.
        client: Supabase client instance.

    Returns:
        Dictionary containing saved credential metadata and validation result.

    Raises:
        HTTPException: 400 if key is empty; 500 if database persistence fails.
    """
    user_id = user.id if hasattr(user, "id") else user.get("id")
    raw_key = payload.raw_key.strip()
    if not raw_key:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="API Key cannot be empty."
        )

    # Optional dry-run verification
    is_valid, verify_msg = validate_provider_key(
        provider=payload.provider,
        raw_key=raw_key,
        api_base=payload.api_base,
        model=payload.custom_model_name
    )

    try:
        saved = save_user_credential(
            client=client,
            user_id=str(user_id),
            provider=payload.provider,
            raw_key=raw_key,
            api_base=payload.api_base,
            custom_model_name=payload.custom_model_name,
            is_valid=is_valid
        )
        return {
            "success": True,
            "credential": saved,
            "validation": {"is_valid": is_valid, "message": verify_msg}
        }
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to save credential: {str(e)}"
        )


@router.delete("/keys/{provider}")
def remove_user_key(
    provider: str,
    custom_model_name: Optional[str] = None,
    user=Depends(login_required),
    client: Client = Depends(get_supabase_client)
):
    """Deletes a stored BYOK credential for a specific provider.

    Args:
        provider: Provider identifier (e.g., 'groq', 'google', 'openai').
        custom_model_name: Optional model name if removing a custom provider entry.
        user: Authenticated user object from dependency.
        client: Supabase client instance.

    Returns:
        Dictionary with boolean 'success' indicator.
    """
    user_id = user.id if hasattr(user, "id") else user.get("id")
    success = delete_user_credential(
        client=client,
        user_id=str(user_id),
        provider=provider,
        custom_model_name=custom_model_name
    )
    return {"success": success}


@router.post("/keys/verify")
def verify_user_key(
    payload: VerifyKeySchema,
    user=Depends(login_required)
):
    """Tests an API key live with a 1-token dry run without saving to the database.

    Args:
        payload: VerifyKeySchema with provider, raw_key, api_base, and model.
        user: Authenticated user object from dependency.

    Returns:
        Dictionary with boolean 'is_valid' and detailed message string.
    """
    is_valid, msg = validate_provider_key(
        provider=payload.provider,
        raw_key=payload.raw_key,
        api_base=payload.api_base,
        model=payload.model
    )
    return {"is_valid": is_valid, "message": msg}


@router.get("/preferences")
def get_preferences(
    user=Depends(login_required),
    client: Client = Depends(get_supabase_client)
):
    """Returns top preferred chat models, active model selection, and free-tier quota status.

    Args:
        user: Authenticated user object from dependency.
        client: Supabase client instance.

    Returns:
        Dictionary containing 'preferences' object and 'quota' status.
    """
    user_id = user.id if hasattr(user, "id") else user.get("id")
    prefs = get_user_preferences(client, str(user_id))
    quota_status = get_free_tier_status(str(user_id))

    return {
        "preferences": prefs,
        "quota": quota_status
    }


@router.put("/preferences")
def update_preferences(
    payload: SavePreferencesSchema,
    user=Depends(login_required),
    client: Client = Depends(get_supabase_client)
):
    """Updates user's preferred models list, active chat model, and fallback flag.

    Args:
        payload: SavePreferencesSchema with active_model, preferred_models, and fallback_enabled.
        user: Authenticated user object from dependency.
        client: Supabase client instance.

    Returns:
        Dictionary with boolean 'success' indicator and saved 'preferences'.

    Raises:
        HTTPException: 400 if preferred_models list is empty.
    """
    user_id = user.id if hasattr(user, "id") else user.get("id")
    if not payload.preferred_models or len(payload.preferred_models) == 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Must select at least 1 preferred model."
        )

    saved = save_user_preferences(
        client=client,
        user_id=str(user_id),
        active_model=payload.active_model,
        preferred_models=payload.preferred_models,
        fallback_enabled=payload.fallback_enabled
    )
    return {"success": True, "preferences": saved}
