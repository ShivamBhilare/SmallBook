import os
from typing import List, Dict, Any, Optional, Tuple
from supabase import Client
import litellm
from litellm import completion

from app.core.crypto import (
    encrypt_api_key,
    decrypt_api_key,
    mask_api_key,
    extract_key_last4,
)

# Suppress verbose LiteLLM debug logs
litellm.suppress_debug_info = True

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


def get_user_credentials(client: Client, user_id: str) -> List[Dict[str, Any]]:
    """
    Returns all configured API credentials for a user with keys safely masked.
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
    Retrieves and decrypts the user's API key strictly in-memory during inference.
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
    Encrypts and persists an API key in user_llm_credentials.
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
        "last_validated_at": "now()",
        "updated_at": "now()"
    }
    
    # Check if record already exists to update
    query = client.table("user_llm_credentials").select("id").eq("user_id", user_id).eq("provider", provider)
    if custom_model_name:
        query = query.eq("custom_model_name", custom_model_name)
    
    existing = query.execute()
    if existing.data and len(existing.data) > 0:
        rec_id = existing.data[0]["id"]
        res = client.table("user_llm_credentials").update(payload).eq("id", rec_id).execute()
    else:
        res = client.table("user_llm_credentials").insert(payload).execute()
        
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
    """Removes a stored credential record for the user."""
    try:
        query = client.table("user_llm_credentials").delete().eq("user_id", user_id).eq("provider", provider)
        if custom_model_name:
            query = query.eq("custom_model_name", custom_model_name)
        query.execute()
        return True
    except Exception as e:
        print(f"Error deleting credential: {e}")
        return False


OBSOLETE_MODEL_MIGRATIONS = {
    "groq/llama-3.3-70b-versatile": "groq/openai/gpt-oss-120b",
    "groq/llama-3.1-8b-instant": "groq/openai/gpt-oss-20b",
    "gemini/gemini-2.0-flash": "gemini/gemini-2.5-flash",
    "gemini/gemini-2.0-flash-lite": "gemini/gemini-2.5-flash",
    "gemini/gemini-1.5-flash": "gemini/gemini-2.5-flash",
}


def sanitize_preferred_models(models: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Sanitizes user preferred models against catalog and migrates deprecated IDs."""
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
    """Saves user's preferred top 3-5 models and fallback configuration."""
    # Ensure between 1 and 6 models are stored
    capped_models = preferred_models[:6] if preferred_models else DEFAULT_PREFERRED_MODELS
    
    payload = {
        "user_id": user_id,
        "active_model": active_model,
        "preferred_models": capped_models,
        "fallback_enabled": fallback_enabled,
        "updated_at": "now()"
    }
    
    try:
        res = client.table("user_llm_preferences").upsert(payload).execute()
        return payload
    except Exception as e:
        print(f"Preferences save error: {e}")
        return payload


def validate_provider_key(
    provider: str,
    raw_key: str,
    api_base: Optional[str] = None,
    model: Optional[str] = None
) -> Tuple[bool, str]:
    """
    Conducts a fast 1-token test call to verify API key validity without incurring significant latency or cost.
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
