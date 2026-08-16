import logging
from typing import List, Optional, Dict, Any
from supabase import Client
from postgrest.exceptions import APIError
from app.services.authentication.auth_service import get_service_role_client

logger = logging.getLogger(__name__)

def infer_llm_provider(model_name: Optional[str]) -> Optional[str]:
    """Infers the LLM provider name from the model identifier string."""
    if not model_name:
        return None
    
    m = model_name.lower().strip()
    if m.startswith("gemini") or "gemini" in m or m.startswith("google"):
        return "google"
    elif m.startswith("gpt") or "openai" in m:
        return "openai"
    elif m.startswith("claude") or "anthropic" in m:
        return "anthropic"
    elif m.startswith("groq") or "llama" in m or "mixtral" in m:
        return "groq"
    elif m.startswith("ollama"):
        return "ollama"
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
) -> Dict[str, Any]:
    """
    Inserts a user or assistant message into the chat_messages table.
    Uses the provided client, falling back to the service role client if needed.
    """
    data: Dict[str, Any] = {
        "notebook_id": notebook_id,
        "role": role,
        "content": content,
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
        logger.warning(f"Failed to insert chat_message via user client ({err}). Retrying with service role client.")
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
    """
    Persists RAG grounding citations linked to a specific assistant message.
    Uses the service role client to satisfy citations RLS policies.
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
    """
    Fetches the persistent chat history for a notebook ordered chronologically,
    joining all corresponding source citations for assistant responses.
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

        # Attach citations to messages
        for msg in messages:
            msg["citations"] = citations_by_msg.get(msg["id"], [])

        return messages
    except APIError as e:
        logger.error(f"Supabase API error fetching chat history for notebook {notebook_id}: {e}")
        return []
    except Exception as e:
        logger.exception(f"Unexpected error loading chat history for notebook {notebook_id}: {e}")
        return []


def clear_chat_history(client: Client, notebook_id: str) -> bool:
    """
    Deletes all chat messages associated with a notebook.
    Citations and dependencies are automatically removed via ON DELETE CASCADE.
    """
    try:
        res = (
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
