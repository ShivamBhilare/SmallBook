"""Chat Service Module.

Handles persistence, retrieval, citation linkage, and model provider routing
for SmallBook notebook conversational interactions.
"""

import json
import logging
from typing import Any, Dict, List, Optional, Tuple

from postgrest.exceptions import APIError
from supabase import Client

from app.services.authentication.auth_service import get_service_role_client

logger = logging.getLogger(__name__)

# Markers used to embed non-user-facing metadata (timings, token counts) into message content
META_PREFIX = "<!--smallbook-meta:"
META_SUFFIX = "-->"


def extract_message_metadata(content: str) -> Tuple[str, Optional[Dict[str, Any]]]:
    """Extracts embedded JSON metadata from message content.

    Parses out hidden HTML comment markers containing serialization metadata
    (such as latency and token counts), returning the clean user-facing text
    and parsed metadata dictionary.

    Args:
        content: Raw message text potentially containing embedded metadata tags.

    Returns:
        Tuple containing:
            - clean_content: Content with metadata marker stripped and trimmed.
            - metadata: Parsed dictionary if valid JSON was found, otherwise None.
    """
    if not content or META_PREFIX not in content:
        return content, None

    start_idx = content.find(META_PREFIX)
    end_idx = content.find(META_SUFFIX, start_idx)
    if start_idx != -1 and end_idx != -1:
        json_str = content[start_idx + len(META_PREFIX):end_idx]
        clean_content = (content[:start_idx] + content[end_idx + len(META_SUFFIX):]).rstrip()
        try:
            meta = json.loads(json_str)
            return clean_content, meta
        except Exception:
            return clean_content, None
    return content, None


def infer_llm_provider(model_name: Optional[str]) -> Optional[str]:
    """Infers the LLM provider identifier from a model name string.

    Uses prefix routing and fallback substring matching to categorize model IDs
    into standard provider keys recognized by the application (e.g., 'groq',
    'google', 'anthropic', 'openai', 'openrouter', or 'custom').

    Args:
        model_name: Name or path of the model (e.g., 'gemini/gemini-2.5-flash',
            'groq/openai/gpt-oss-120b', 'claude-3-5-sonnet').

    Returns:
        Canonical provider string identifier, or None if model_name is empty.
    """
    if not model_name:
        return None

    m = model_name.lower().strip()

    # 1. Prefix-based routing (handles compound prefixes such as 'groq/openai/gpt-oss-120b')
    if m.startswith("groq/") or m.startswith("groq"):
        return "groq"
    elif m.startswith("gemini/") or m.startswith("gemini") or m.startswith("google"):
        return "google"
    elif m.startswith("openrouter/") or m.startswith("openrouter"):
        return "openrouter"
    elif m.startswith("anthropic/") or m.startswith("claude"):
        return "anthropic"
    elif m.startswith("ollama/"):
        return "custom"
    elif m.startswith("openai/") or m.startswith("gpt") or m.startswith("o1") or m.startswith("o3"):
        return "openai"

    # 2. Substring matching for un-prefixed or shorthand model strings
    if "groq" in m or "llama" in m or "mixtral" in m:
        return "groq"
    elif "gemini" in m or "google" in m:
        return "google"
    elif "claude" in m or "anthropic" in m:
        return "anthropic"
    elif "gpt" in m or "openai" in m:
        return "openai"
    elif "/" in m:
        return m.split("/")[0]

    return "custom"


def save_chat_message(
    client: Client,
    notebook_id: str,
    role: str,
    content: str,
    parent_id: Optional[str] = None,
    llm_provider: Optional[str] = None,
    llm_model: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Inserts a user or assistant message into the chat_messages table.

    Embeds telemetry and timing metadata into content if provided. Tries insertion
    with the provided authenticated user client first, falling back to service-role
    client if permissions or RLS policies demand elevated privileges.

    Args:
        client: Authenticated Supabase client instance.
        notebook_id: UUID of the notebook workspace.
        role: Author role ('user' or 'assistant').
        content: Raw markdown text of the message.
        parent_id: Optional UUID of the parent message in thread.
        llm_provider: Provider key (e.g. 'groq', 'google') for assistant responses.
        llm_model: Exact model identifier used for generation.
        metadata: Optional dictionary with metrics (e.g. timings_ms, used_tokens).

    Returns:
        Dictionary representation of the newly inserted chat_messages row.

    Raises:
        RuntimeError: If database insertion fails across both user and admin clients.
    """
    stored_content = content
    if metadata:
        try:
            meta_json = json.dumps(metadata)
            stored_content = f"{content}\n\n{META_PREFIX}{meta_json}{META_SUFFIX}"
        except Exception as e:
            logger.warning(f"Failed to serialize chat message metadata: {e}")

    data: Dict[str, Any] = {
        "notebook_id": notebook_id,
        "role": role,
        "content": stored_content,
        "is_summarized": False,
    }
    if parent_id:
        data["parent_id"] = parent_id
    if llm_provider:
        data["llm_provider"] = llm_provider
    if llm_model:
        data["llm_model"] = llm_model

    try:
        res = client.table("chat_messages").insert(data).execute()
        if res.data:
            return res.data[0]
    except Exception as err:
        logger.warning(
            f"Failed to insert chat_message via user client ({err}). "
            "Retrying with service role client."
        )
        try:
            admin_client = get_service_role_client()
            res = admin_client.table("chat_messages").insert(data).execute()
            if res.data:
                return res.data[0]
        except Exception as admin_err:
            logger.error(f"Failed to insert chat message with service role: {admin_err}")
            raise admin_err

    raise RuntimeError("Failed to insert chat message record into database.")


def save_citations(
    chat_message_id: str,
    citations_data: List[Dict[str, Any]]
) -> List[Dict[str, Any]]:
    """Persists RAG grounding citations linked to an assistant chat message.

    Uses elevated service-role permissions to ensure citation records are
    successfully attached regardless of row-level security constraints on
    individual chunk references.

    Args:
        chat_message_id: UUID of the assistant chat message row.
        citations_data: List of citation dictionaries containing chunk references,
            page numbers, document titles, and relevance scores.

    Returns:
        List of inserted citation database records, or empty list on failure.
    """
    if not citations_data:
        return []

    records = []
    for cit in citations_data:
        record: Dict[str, Any] = {
            "chat_message_id": chat_message_id,
            "source_title": cit.get("source_title") or cit.get("document_title") or "Document",
        }
        if "chunk_id" in cit and cit["chunk_id"]:
            record["chunk_id"] = cit["chunk_id"]
        elif "id" in cit and cit["id"]:
            record["chunk_id"] = cit["id"]

        if "page_number" in cit and cit["page_number"] is not None:
            record["page_number"] = cit["page_number"]
        elif "order" in cit and cit["order"] is not None:
            record["page_number"] = cit["order"] + 1

        if "chunk_snapshot" in cit and cit["chunk_snapshot"]:
            record["chunk_snapshot"] = cit["chunk_snapshot"]
        elif "text_snippet" in cit and cit["text_snippet"]:
            record["chunk_snapshot"] = cit["text_snippet"]

        if "relevance_score" in cit and cit["relevance_score"] is not None:
            record["relevance_score"] = float(cit["relevance_score"])

        records.append(record)

    try:
        admin_client = get_service_role_client()
        res = admin_client.table("citations").insert(records).execute()
        return res.data or []
    except Exception as err:
        logger.error(f"Error saving citations for chat message {chat_message_id}: {err}")
        return []


def get_chat_history(client: Client, notebook_id: str) -> List[Dict[str, Any]]:
    """Fetches chronological chat history for a notebook with attached citations.

    Queries messages in ascending creation order, batches citation lookups
    for all assistant responses, and unpacks embedded performance metadata.

    Args:
        client: Authenticated Supabase client instance.
        notebook_id: UUID of the target notebook.

    Returns:
        List of message dictionaries with 'citations', 'timings_ms', and
        'used_tokens' populated, or empty list if no messages exist or on error.
    """
    try:
        msg_res = (
            client.table("chat_messages")
            .select("*")
            .eq("notebook_id", notebook_id)
            .order("created_at", desc=False)
            .execute()
        )
        messages = msg_res.data or []
        if not messages:
            return []

        # Find assistant message IDs to query citations in batch
        assistant_msg_ids = [m["id"] for m in messages if m.get("role") == "assistant"]
        citations_by_msg: Dict[str, List[Dict[str, Any]]] = {}

        if assistant_msg_ids:
            try:
                cit_res = (
                    client.table("citations")
                    .select("*")
                    .in_("chat_message_id", assistant_msg_ids)
                    .order("created_at", desc=False)
                    .execute()
                )
                for cit in (cit_res.data or []):
                    mid = cit["chat_message_id"]
                    if mid not in citations_by_msg:
                        citations_by_msg[mid] = []
                    citations_by_msg[mid].append(cit)
            except Exception as cit_err:
                logger.warning(f"Error loading citations for notebook {notebook_id}: {cit_err}")

        # Attach citations and unpack embedded metadata into top-level keys
        for msg in messages:
            msg["citations"] = citations_by_msg.get(msg["id"], [])
            clean_content, meta = extract_message_metadata(msg.get("content", ""))
            msg["content"] = clean_content
            if meta:
                msg["timings_ms"] = meta.get("timings_ms")
                msg["used_tokens"] = meta.get("used_tokens")

        return messages
    except APIError as e:
        logger.error(f"Supabase API error fetching chat history for notebook {notebook_id}: {e}")
        return []
    except Exception as e:
        logger.exception(f"Unexpected error loading chat history for notebook {notebook_id}: {e}")
        return []


def clear_chat_history(client: Client, notebook_id: str) -> bool:
    """Deletes all chat messages associated with a notebook workspace.

    Child citations are automatically removed via database foreign-key
    CASCADE constraints. Tries deletion via user client before falling back
    to service-role client.

    Args:
        client: Authenticated Supabase client instance.
        notebook_id: UUID of the notebook whose history should be cleared.

    Returns:
        True if history was cleared successfully.

    Raises:
        Exception: If admin fallback client also fails to delete records.
    """
    try:
        (
            client.table("chat_messages")
            .delete()
            .eq("notebook_id", notebook_id)
            .execute()
        )
        return True
    except Exception as err:
        logger.error(f"Error clearing chat history for notebook {notebook_id}: {err}")
        try:
            admin_client = get_service_role_client()
            admin_client.table("chat_messages").delete().eq("notebook_id", notebook_id).execute()
            return True
        except Exception as admin_err:
            logger.error(f"Admin fallback failed to clear chat history: {admin_err}")
            raise admin_err
