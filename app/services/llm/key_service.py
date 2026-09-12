"""
Bring-Your-Own-Key (BYOK) Credential & Model Management Service

Coordinates user-provided LLM API credentials, model preferences, and validation:
    1. Cryptographic Key Persistence: Encrypts API keys using AES-256-GCM before DB write
       and decrypts strictly in-memory during inference.
    2. Provider & Model Catalogs: Maintains known model endpoints, tokens, and badges
       for Groq, Google Gemini, OpenAI, Anthropic, OpenRouter, and Ollama/vLLM.
    3. User Preferences: Stores top 1-5 active models and cascading fallback settings.
    4. Fast Verification: Tests newly submitted keys with a 1-token probe request.
"""

from datetime import datetime, timezone
from typing import List, Dict, Any, Optional, Tuple
from supabase import Client
import litellm
from litellm import completion

from app.core.crypto import (
    encrypt_api_key,
    decrypt_api_key,
    extract_key_last4,
)

# Suppress verbose LiteLLM debug logs to preserve clean terminal and production logging
litellm.suppress_debug_info = True

# Default fallback model rankings offered to users without custom model configurations
DEFAULT_PREFERRED_MODELS = [
    {
        "id": "groq/openai/gpt-oss-120b",
        "provider": "groq",
        "name": "Groq GPT-OSS 120B",
        "badge": "Primary Free",
        "is_free": True,
        "context_window": 128000,
    },
    {
        "id": "gemini/gemini-2.5-flash",
        "provider": "google",
        "name": "Gemini 2.5 Flash",
        "badge": "Fast & Free",
        "is_free": True,
        "context_window": 1000000,
    },
    {
        "id": "groq/openai/gpt-oss-20b",
        "provider": "groq",
        "name": "Groq GPT-OSS 20B",
        "badge": "Ultra Fast",
        "is_free": True,
        "context_window": 128000,
    },
    {
        "id": "gpt-4o",
        "provider": "openai",
        "name": "OpenAI GPT-4o",
        "badge": "Pro",
        "is_free": False,
        "context_window": 128000,
    },
    {
        "id": "claude-3-5-sonnet-20241022",
        "provider": "anthropic",
        "name": "Claude 3.5 Sonnet",
        "badge": "Pro",
        "is_free": False,
        "context_window": 200000,
    },
]

# Comprehensive provider catalog used for UI provider tabs, key URLs, and model selection
PROVIDER_CATALOG = [
    {
        "id": "groq",
        "name": "Groq",
        "icon": "bolt",
        "free_key_url": "https://console.groq.com/keys",
        "free_key_text": "Get Free Groq Key (14.4k/day)",
        "models": [
            {"id": "groq/openai/gpt-oss-120b", "name": "GPT-OSS 120B (Recommended)", "is_free": True},
            {"id": "groq/openai/gpt-oss-20b", "name": "GPT-OSS 20B (Ultra Fast)", "is_free": True},
            {"id": "groq/groq/compound-mini", "name": "Compound Mini", "is_free": True},
            {"id": "groq/qwen/qwen3.6-27b", "name": "Qwen 3.6 27B", "is_free": True},
        ]
    },
    {
        "id": "google",
        "name": "Google Gemini",
        "icon": "auto_awesome",
        "free_key_url": "https://aistudio.google.com/app/apikey",
        "free_key_text": "Get Free Gemini Key (1.5k/day)",
        "models": [
            {"id": "gemini/gemini-2.5-flash", "name": "Gemini 2.5 Flash (Recommended)", "is_free": True},
        ]
    },
    {
        "id": "openai",
        "name": "OpenAI",
        "icon": "smart_toy",
        "free_key_url": "https://platform.openai.com/api-keys",
        "free_key_text": "OpenAI Platform Keys",
        "models": [
            {"id": "gpt-4o", "name": "GPT-4o (Flagship)", "is_free": False},
            {"id": "gpt-4o-mini", "name": "GPT-4o Mini (Affordable)", "is_free": False},
            {"id": "o1-mini", "name": "o1-mini (Reasoning)", "is_free": False},
            {"id": "o3-mini", "name": "o3-mini (Next-Gen)", "is_free": False},
        ]
    },
    {
        "id": "anthropic",
        "name": "Anthropic Claude",
        "icon": "psychology",
        "free_key_url": "https://console.anthropic.com/settings/keys",
        "free_key_text": "Anthropic Console",
        "models": [
            {"id": "claude-3-5-sonnet-20241022", "name": "Claude 3.5 Sonnet", "is_free": False},
            {"id": "claude-3-5-haiku-20241022", "name": "Claude 3.5 Haiku", "is_free": False},
        ]
    },
    {
        "id": "openrouter",
        "name": "OpenRouter",
        "icon": "hub",
        "free_key_url": "https://openrouter.ai/keys",
        "free_key_text": "OpenRouter Dashboard",
        "models": [
            {"id": "openrouter/auto", "name": "OpenRouter Auto Router", "is_free": False},
            {"id": "openrouter/deepseek/deepseek-r1", "name": "DeepSeek R1", "is_free": False},
            {"id": "openrouter/meta-llama/llama-3.3-70b-instruct", "name": "Llama 3.3 70B", "is_free": False},
        ]
    },
    {
        "id": "custom",
        "name": "Custom / Local (Ollama, vLLM)",
        "icon": "terminal",
        "free_key_url": "https://ollama.com",
        "free_key_text": "Ollama Local AI",
        "models": [
            {"id": "ollama/llama3.2", "name": "Ollama Llama 3.2 (Local)", "is_free": True},
            {"id": "custom/vllm", "name": "Custom vLLM / OpenAI Endpoint", "is_free": False},
        ]
    }
]


# =========================================================================
# 1. CREDENTIAL CRUD & DECRYPTION
# =========================================================================

def get_user_credentials(client: Client, user_id: str) -> List[Dict[str, Any]]:
    """
    Returns all configured API credentials for a user with keys safely masked.

    Omits `api_key_encrypted` from the SELECT statement to prevent accidental exposure,
    returning only non-sensitive metadata (`key_last4`, `is_valid`, etc.).

    Args:
        client: Active Supabase client.
        user_id: UUID string of the authenticated user.

    Returns:
        List[Dict[str, Any]]: Masked credential records.
    """
    try:
        res = client.table("user_llm_credentials").select(
            "id, provider, key_last4, api_base, custom_model_name, is_active, is_valid, last_validated_at, created_at, updated_at"
        ).eq("user_id", user_id).execute()
        return res.data or []
    except Exception as e:
        print(f"Error fetching user credentials: {e}")
        return []


def get_decrypted_user_key(
    client: Client,
    user_id: str,
    provider: str,
    custom_model_name: Optional[str] = None
) -> Optional[Dict[str, Any]]:
    """
    Retrieves and decrypts a user's API key strictly in-memory during inference.

    Fetches the ciphertext from `user_llm_credentials` and applies AES-256-GCM
    authenticated decryption. The plaintext key is never written to disk or logs.

    Args:
        client: Active Supabase client.
        user_id: UUID string of the user.
        provider: Provider identifier (e.g. 'groq', 'openai', 'anthropic').
        custom_model_name: Optional custom model name for provider disambiguation.

    Returns:
        Optional[Dict[str, Any]]: Dictionary with plaintext `api_key` and config, or None.
    """
    try:
        query = client.table("user_llm_credentials").select("*").eq("user_id", user_id).eq("provider", provider).eq("is_active", True)
        if custom_model_name:
            query = query.eq("custom_model_name", custom_model_name)
        
        res = query.execute()
        if not res.data or len(res.data) == 0:
            return None
        
        record = res.data[0]
        encrypted_str = record.get("api_key_encrypted")
        if not encrypted_str:
            return None
        
        decrypted_key = decrypt_api_key(encrypted_str)
        return {
            "api_key": decrypted_key,
            "api_base": record.get("api_base"),
            "provider": provider,
            "custom_model_name": record.get("custom_model_name"),
            "key_last4": record.get("key_last4")
        }
    except Exception as e:
        print(f"Failed to decrypt user key for provider {provider}: {e}")
        return None


def save_user_credential(
    client: Client,
    user_id: str,
    provider: str,
    raw_key: str,
    api_base: Optional[str] = None,
    custom_model_name: Optional[str] = None,
    is_valid: bool = True
) -> Dict[str, Any]:
    """
    Encrypts and persists an API key in `user_llm_credentials`.

    Encrypts the plaintext key via AES-256-GCM, extracts the last 4 characters for
    user verification, and upserts the record in the database.

    Args:
        client: Active Supabase client.
        user_id: UUID string of the user.
        provider: Provider identifier (e.g. 'groq', 'google', 'openai').
        raw_key: Plaintext API key string.
        api_base: Optional custom API base endpoint URL.
        custom_model_name: Optional custom model identifier.
        is_valid: Boolean verification status from validation probe.

    Returns:
        Dict[str, Any]: Saved credential summary with masked details.
    """
    encrypted_key = encrypt_api_key(raw_key)
    last4 = extract_key_last4(raw_key)
    
    payload = {
        "user_id": user_id,
        "provider": provider.lower().strip(),
        "api_key_encrypted": encrypted_key,
        "key_last4": last4,
        "api_base": api_base.strip() if api_base else None,
        "custom_model_name": custom_model_name.strip() if custom_model_name else None,
        "is_active": True,
        "is_valid": is_valid,
        "last_validated_at": datetime.now(timezone.utc).isoformat(),
        "updated_at": datetime.now(timezone.utc).isoformat()
    }
    
    # Check if record already exists to update
    query = client.table("user_llm_credentials").select("id").eq("user_id", user_id).eq("provider", provider)
    if custom_model_name:
        query = query.eq("custom_model_name", custom_model_name)
    
    existing = query.execute()
    if existing.data and len(existing.data) > 0:
        rec_id = existing.data[0]["id"]
        client.table("user_llm_credentials").update(payload).eq("id", rec_id).execute()
    else:
        client.table("user_llm_credentials").insert(payload).execute()
        
    return {
        "provider": provider,
        "key_last4": last4,
        "api_base": api_base,
        "custom_model_name": custom_model_name,
        "is_valid": is_valid
    }


def delete_user_credential(
    client: Client,
    user_id: str,
    provider: str,
    custom_model_name: Optional[str] = None
) -> bool:
    """
    Removes a stored credential record for the user.

    Args:
        client: Active Supabase client.
        user_id: UUID string of the user.
        provider: Provider identifier to delete.
        custom_model_name: Optional custom model name filter.

    Returns:
        bool: True if deletion succeeded, False on error.
    """
    try:
        query = client.table("user_llm_credentials").delete().eq("user_id", user_id).eq("provider", provider)
        if custom_model_name:
            query = query.eq("custom_model_name", custom_model_name)
        query.execute()
        return True
    except Exception as e:
        print(f"Error deleting credential: {e}")
        return False


# Mapping of deprecated model identifiers to active production equivalents
OBSOLETE_MODEL_MIGRATIONS = {
    "groq/llama-3.3-70b-versatile": "groq/openai/gpt-oss-120b",
    "groq/llama-3.1-8b-instant": "groq/openai/gpt-oss-20b",
    "gemini/gemini-2.0-flash": "gemini/gemini-2.5-flash",
    "gemini/gemini-2.0-flash-lite": "gemini/gemini-2.5-flash",
    "gemini/gemini-1.5-flash": "gemini/gemini-2.5-flash",
}


# =========================================================================
# 2. USER MODEL PREFERENCES & MIGRATIONS
# =========================================================================

def sanitize_preferred_models(models: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Sanitizes user preferred models against catalog and migrates deprecated IDs.

    Ensures that deprecated or renamed models (e.g. older Llama or Gemini versions)
    are seamlessly mapped to their current equivalents without breaking user dropdowns.
    Caps the returned list at 5 models.

    Args:
        models: List of model preference dictionaries or ID strings.

    Returns:
        List[Dict[str, Any]]: Sanitized list of up to 5 preferred model objects.
    """
    catalog_map = {}
    for p in PROVIDER_CATALOG:
        for m in p.get("models", []):
            catalog_map[m["id"]] = {
                "id": m["id"],
                "name": m.get("name", m["id"]),
                "provider": p["id"],
                "badge": "Free" if m.get("is_free") else "BYOK",
                "is_free": m.get("is_free", False)
            }

    sanitized = []
    seen = set()
    for item in (models or []):
        m_id = item.get("id") if isinstance(item, dict) else str(item)
        migrated_id = OBSOLETE_MODEL_MIGRATIONS.get(m_id, m_id)
        if migrated_id in catalog_map and migrated_id not in seen:
            sanitized.append(catalog_map[migrated_id])
            seen.add(migrated_id)
        elif isinstance(item, dict) and item.get("id") and m_id not in seen:
            sanitized.append(item)
            seen.add(m_id)

    return sanitized[:5] if sanitized else list(DEFAULT_PREFERRED_MODELS)


def get_user_preferences(client: Client, user_id: str) -> Dict[str, Any]:
    """
    Retrieves user preferences for top 1-5 chat dropdown models and fallback settings.

    Args:
        client: Active Supabase client.
        user_id: UUID string of the authenticated user.

    Returns:
        Dict[str, Any]: Dictionary containing `active_model`, `preferred_models`, and `fallback_enabled`.
    """
    try:
        res = client.table("user_llm_preferences").select("*").eq("user_id", user_id).execute()
        if res.data and len(res.data) > 0:
            row = res.data[0]
            raw_models = row.get("preferred_models") or DEFAULT_PREFERRED_MODELS
            models = sanitize_preferred_models(raw_models)
            active = row.get("active_model")
            active = OBSOLETE_MODEL_MIGRATIONS.get(active, active)
            if not active or not any(m["id"] == active for m in models):
                active = models[0]["id"]
            return {
                "active_model": active,
                "preferred_models": models,
                "fallback_enabled": row.get("fallback_enabled", True)
            }
    except Exception as e:
        print(f"Preferences fetch error (falling back to defaults): {e}")

    return {
        "active_model": DEFAULT_PREFERRED_MODELS[0]["id"],
        "preferred_models": list(DEFAULT_PREFERRED_MODELS),
        "fallback_enabled": True
    }


def save_user_preferences(
    client: Client,
    user_id: str,
    active_model: str,
    preferred_models: List[Dict[str, Any]],
    fallback_enabled: bool = True
) -> Dict[str, Any]:
    """
    Saves user's preferred top 3-5 models and fallback configuration.

    Args:
        client: Active Supabase client.
        user_id: UUID string of the authenticated user.
        active_model: ID string of the primary selected model.
        preferred_models: List of model configuration objects (capped at 5).
        fallback_enabled: Whether cascading fallback to free-tier is allowed.

    Returns:
        Dict[str, Any]: The persisted preferences payload.
    """
    # Ensure top 3-5 models are stored
    capped_models = preferred_models[:5] if preferred_models else DEFAULT_PREFERRED_MODELS
    
    payload = {
        "user_id": user_id,
        "active_model": active_model,
        "preferred_models": capped_models,
        "fallback_enabled": fallback_enabled,
        "updated_at": datetime.now(timezone.utc).isoformat()
    }
    
    try:
        client.table("user_llm_preferences").upsert(payload).execute()
        return payload
    except Exception as e:
        print(f"Preferences save error: {e}")
        return payload


# =========================================================================
# 3. LIVE PROVIDER KEY VALIDATION PROBE
# =========================================================================

def validate_provider_key(
    provider: str,
    raw_key: str,
    api_base: Optional[str] = None,
    model: Optional[str] = None
) -> Tuple[bool, str]:
    """
    Conducts a fast 1-token test call to verify API key validity with minimal latency and zero cost.

    Dispatches a minimal completion query (`ping`, `max_tokens=1`) through LiteLLM.
    Categorizes errors into human-readable error explanations (Authentication, RateLimit, Timeout).

    Args:
        provider: Provider identifier (e.g. 'groq', 'google', 'openai', 'anthropic', 'custom').
        raw_key: Plaintext API key submitted by the user.
        api_base: Optional custom endpoint URL.
        model: Optional specific model ID to test against.

    Returns:
        Tuple[bool, str]: (is_valid, status_message).
    """
    p = provider.lower().strip()
    test_model = model
    if not test_model:
        if p == "groq":
            test_model = "groq/openai/gpt-oss-120b"
        elif p == "google" or p == "gemini":
            test_model = "gemini/gemini-2.5-flash"
        elif p == "openai":
            test_model = "gpt-4o-mini"
        elif p == "anthropic":
            test_model = "claude-3-5-haiku-20241022"
        elif p == "openrouter":
            test_model = "openrouter/auto"
        elif p == "custom":
            test_model = model or "ollama/llama3.2"
        else:
            test_model = f"{p}/test"

    try:
        kwargs = {
            "model": test_model,
            "messages": [{"role": "user", "content": "ping"}],
            "max_tokens": 1,
            "timeout": 12,
        }
        if raw_key and raw_key.strip():
            kwargs["api_key"] = raw_key.strip()
        if api_base and api_base.strip():
            kwargs["api_base"] = api_base.strip()

        resp = completion(**kwargs)
        if resp and resp.choices:
            return (True, f"Key verified successfully! (Provider: {provider.capitalize()})")
        return (False, "Provider responded with an empty test payload.")
    except Exception as err:
        err_msg = str(err)
        # Simplify error message for user display
        if "AuthenticationError" in err_msg or "401" in err_msg or "invalid_api_key" in err_msg:
            return (False, "Invalid API Key: Authentication failed with provider.")
        if "RateLimitError" in err_msg or "429" in err_msg:
            return (False, "Provider rate limit reached (429). Key is recognized but currently rate-limited.")
        if "ConnectionError" in err_msg or "timeout" in err_msg.lower():
            return (False, "Connection timeout: Provider endpoint could not be reached.")
        return (False, f"Verification failed: {err_msg[:160]}")

