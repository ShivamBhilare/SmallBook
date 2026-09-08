import logging
from typing import List, Dict, Any, Optional
from datetime import datetime, timezone
from supabase import Client

logger = logging.getLogger(__name__)


def list_notebook_notes(supabase: Client, notebook_id: str, user_id: str) -> List[Dict[str, Any]]:
    """Fetches all notes for a given notebook ordered by updated_at desc."""
    try:
        res = (
            supabase.table("notes")
            .select("id, notebook_id, user_id, title, content, source_message_id, created_at, updated_at")
            .eq("notebook_id", notebook_id)
            .eq("user_id", user_id)
            .order("updated_at", desc=True)
            .execute()
        )
        return res.data or []
    except Exception as e:
        logger.error(f"Error fetching notes for notebook {notebook_id}: {e}")
        return []


def get_note_by_id(supabase: Client, note_id: str, user_id: str) -> Optional[Dict[str, Any]]:
    """Fetches a specific note by ID."""
    try:
        res = (
            supabase.table("notes")
            .select("*")
            .eq("id", note_id)
            .eq("user_id", user_id)
            .execute()
        )
        if not res.data:
            return None
        return res.data[0]
    except Exception as e:
        logger.error(f"Error fetching note {note_id}: {e}")
        return None


def create_note(
    supabase: Client,
    notebook_id: str,
    user_id: str,
    title: Optional[str],
    content: str,
    source_message_id: Optional[str] = None
) -> Dict[str, Any]:
    """Creates a new note in the database."""
    clean_title = (title or "").strip() or "Untitled Note"
    payload: Dict[str, Any] = {
        "notebook_id": notebook_id,
        "user_id": user_id,
        "title": clean_title,
        "content": content,
    }
    if source_message_id:
        payload["source_message_id"] = source_message_id

    res = supabase.table("notes").insert(payload).execute()
    if not res.data:
        raise ValueError("Failed to create note in database.")
    return res.data[0]


def update_note(
    supabase: Client,
    note_id: str,
    user_id: str,
    title: Optional[str] = None,
    content: Optional[str] = None
) -> Optional[Dict[str, Any]]:
    """Updates title and/or content of an existing note."""
    update_payload: Dict[str, Any] = {}
    if title is not None:
        update_payload["title"] = title.strip() or "Untitled Note"
    if content is not None:
        update_payload["content"] = content
    if not update_payload:
        return get_note_by_id(supabase, note_id, user_id)

    # Set explicit ISO updated_at timestamp
    update_payload["updated_at"] = datetime.now(timezone.utc).isoformat()
    res = (
        supabase.table("notes")
        .update(update_payload)
        .eq("id", note_id)
        .eq("user_id", user_id)
        .execute()
    )
    if not res.data:
        return None
    return res.data[0]


def delete_note(supabase: Client, note_id: str, user_id: str) -> bool:
    """Deletes a note from the database."""
    try:
        res = (
            supabase.table("notes")
            .delete()
            .eq("id", note_id)
            .eq("user_id", user_id)
            .execute()
        )
        return bool(res.data)
    except Exception as e:
        logger.error(f"Error deleting note {note_id}: {e}")
        return False
