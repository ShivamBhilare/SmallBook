from typing import Optional, Generator, List, Dict, Any, Tuple
import litellm
from litellm import completion

from app.services.llm.free_tier import (
    get_developer_groq_key,
    get_developer_gemini_key,
)

# Suppress verbose debug logs in production
litellm.suppress_debug_info = True


def generate_llm_response(
    prompt: str,
    system_instruction: str = "You are a helpful, strictly constrained AI assistant.",
    model: str = "groq/openai/gpt-oss-120b",
    api_key: Optional[str] = None,
    api_base: Optional[str] = None,
    temperature: float = 0.2,
    max_tokens: int = 4096,
    **kwargs
) -> str:
    """
    Sends prompts to any supported LLM provider using LiteLLM.
    Accepts in-memory decrypted user API keys or custom endpoints.
    """
    messages = [
        {"role": "system", "content": system_instruction},
        {"role": "user", "content": prompt}
    ]

    call_kwargs = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
        **kwargs
    }
    if api_key and api_key.strip():
        call_kwargs["api_key"] = api_key.strip()
    if api_base and api_base.strip():
        call_kwargs["api_base"] = api_base.strip()

    try:
        response = completion(**call_kwargs)
        return response.choices[0].message.content.strip()
    except Exception as e:
        return f"Error executing LLM request ({model}): {str(e)}"


def stream_llm_response(
    prompt: str,
    system_instruction: str = "You are a helpful, strictly constrained AI assistant.",
    model: str = "groq/openai/gpt-oss-120b",
    api_key: Optional[str] = None,
    api_base: Optional[str] = None,
    temperature: float = 0.2,
    max_tokens: int = 4096,
    **kwargs
) -> Generator[str, None, None]:
    """Streams response chunks for real-time frontend chat interfaces."""
    messages = [
        {"role": "system", "content": system_instruction},
        {"role": "user", "content": prompt}
    ]

    call_kwargs = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "stream": True,
        **kwargs
    }
    if api_key and api_key.strip():
        call_kwargs["api_key"] = api_key.strip()
    if api_base and api_base.strip():
        call_kwargs["api_base"] = api_base.strip()

    try:
        response = completion(**call_kwargs)
        for chunk in response:
            if hasattr(chunk, "choices") and chunk.choices and len(chunk.choices) > 0:
                delta = chunk.choices[0].delta
                if hasattr(delta, "content") and delta.content:
                    yield delta.content
    except Exception as e:
        yield f"\n\n[Stream Error ({model}): {str(e)}]"


def stream_resilient_llm_response(
    prompt: str,
    system_instruction: str = "You are a helpful, strictly constrained AI assistant.",
    requested_model: str = "groq/openai/gpt-oss-120b",
    user_primary_key: Optional[str] = None,
    user_primary_base: Optional[str] = None,
    user_backup_credentials: Optional[List[Dict[str, Any]]] = None,
    fallback_enabled: bool = True,
    temperature: float = 0.2,
    max_tokens: int = 4096,
    **kwargs
) -> Generator[Tuple[str, Any], None, None]:
    """
    Cascading resilient LLM streaming generator.
    Yields (event_type, payload) tuples:
      - ("chunk", "token string")
      - ("fallback_notice", {"original_model": "...", "fallback_model": "...", "reason": "..."})
      - ("used_model", "actual_model_name")
      - ("error", "error message")
    """
    # 1. Build Candidate Chain
    candidates: List[Dict[str, Any]] = []

    # Candidate 1: Requested model with user key (if provided) or developer key
    primary_key = user_primary_key
    if not primary_key:
        if "groq" in requested_model.lower():
            primary_key = get_developer_groq_key()
        elif "gemini" in requested_model.lower() or "google" in requested_model.lower():
            primary_key = get_developer_gemini_key()
            
    candidates.append({
        "model": requested_model,
        "api_key": primary_key,
        "api_base": user_primary_base,
        "label": requested_model,
        "tier": "user_primary" if user_primary_key else "system_primary"
    })

    if fallback_enabled:
        # Candidate 2: User's other stored keys (if any)
        if user_backup_credentials:
            for cred in user_backup_credentials:
                provider = cred.get("provider", "")
                backup_key = cred.get("api_key")
                backup_base = cred.get("api_base")
                
                # Pick best default model for this provider
                backup_model = None
                if provider == "groq":
                    backup_model = "groq/openai/gpt-oss-120b"
                elif provider == "google" or provider == "gemini":
                    backup_model = "gemini/gemini-2.5-flash"
                elif provider == "openai":
                    backup_model = "gpt-4o-mini"
                elif provider == "anthropic":
                    backup_model = "claude-3-5-haiku-20241022"
                elif provider == "custom" and cred.get("custom_model_name"):
                    backup_model = cred.get("custom_model_name")

                if backup_model and backup_model != requested_model and backup_key:
                    candidates.append({
                        "model": backup_model,
                        "api_key": backup_key,
                        "api_base": backup_base,
                        "label": f"{provider.capitalize()} User Key ({backup_model})",
                        "tier": "user_backup"
                    })

        # Candidate 3: Developer Groq Free Tier
        dev_groq_key = get_developer_groq_key()
        if dev_groq_key and requested_model != "groq/openai/gpt-oss-120b":
            candidates.append({
                "model": "groq/openai/gpt-oss-120b",
                "api_key": dev_groq_key,
                "api_base": None,
                "label": "Groq GPT-OSS 120B Free Tier",
                "tier": "developer_groq"
            })

        # Candidate 4: Developer Gemini 2.5 Flash Free Tier
        dev_gemini_key = get_developer_gemini_key()
        if dev_gemini_key and requested_model != "gemini/gemini-2.5-flash":
            candidates.append({
                "model": "gemini/gemini-2.5-flash",
                "api_key": dev_gemini_key,
                "api_base": None,
                "label": "Google Gemini 2.5 Flash Free Tier",
                "tier": "developer_gemini"
            })

    # 2. Iterate through candidates until one streams successfully
    messages = [
        {"role": "system", "content": system_instruction},
        {"role": "user", "content": prompt}
    ]

    last_error = None
    stream_started = False

    for idx, candidate in enumerate(candidates):
        model_name = candidate["model"]
        cand_key = candidate["api_key"]
        cand_base = candidate["api_base"]

        call_kwargs = {
            "model": model_name,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": True,
            **kwargs
        }
        if cand_key and cand_key.strip():
            call_kwargs["api_key"] = cand_key.strip()
        if cand_base and cand_base.strip():
            call_kwargs["api_base"] = cand_base.strip()

        try:
            response = completion(**call_kwargs)

            # If this is a successful fallback candidate, notify frontend
            if idx > 0:
                reason = str(last_error) if last_error else "Provider unavailable"
                if "401" in reason or "AuthenticationError" in reason:
                    clean_reason = "API key authentication failed. Switched to backup provider."
                elif "429" in reason or "RateLimit" in reason:
                    clean_reason = "Rate limit reached (429). Switched to backup provider."
                elif "404" in reason or "not found" in reason.lower():
                    clean_reason = "Selected model unavailable. Switched to backup provider."
                elif "403" in reason or "Forbidden" in reason:
                    clean_reason = "API access restricted (403). Switched to backup provider."
                else:
                    clean_reason = "Primary provider unavailable. Switched to backup provider."

                yield ("fallback_notice", {
                    "original_model": requested_model,
                    "fallback_model": model_name,
                    "fallback_label": candidate["label"],
                    "reason": clean_reason
                })

            yield ("used_model", model_name)
            
            for chunk in response:
                if hasattr(chunk, "choices") and chunk.choices and len(chunk.choices) > 0:
                    delta = chunk.choices[0].delta
                    if hasattr(delta, "content") and delta.content:
                        stream_started = True
                        yield ("chunk", delta.content)

            # Successfully streamed full response!
            return

        except Exception as err:
            last_error = err
            # If we already yielded tokens to the user, we cannot switch mid-sentence without messy UI
            if stream_started:
                yield ("chunk", f"\n\n[Generation Interrupted: {str(err)}]")
                return

    # If all candidates failed
    err_str = str(last_error) if last_error else "Unknown error"
    if "Missing" in err_str and "API key" in err_str or "API_KEY" in err_str:
        clean_msg = "No active API key configured for this model. Please add your free Groq or Gemini API key in Key Settings (top-right) to continue chatting."
    elif "401" in err_str or "AuthenticationError" in err_str or "invalid_api_key" in err_str:
        clean_msg = "API key authentication failed. Please check your API key in Key Settings."
    elif "429" in err_str or "RateLimit" in err_str:
        clean_msg = "Rate limit reached. Please wait a few moments or add a backup provider key in Key Settings."
    else:
        clean_first_line = err_str.splitlines()[0] if err_str else "Provider unavailable."
        clean_msg = f"Unable to reach the AI model: {clean_first_line}"

    yield ("error", clean_msg)