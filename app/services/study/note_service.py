"""Note Persistence & Management Service.

Provides CRUD operations for user notes within a notebook workspace,
supporting rich Markdown content and references back to source chat messages.
"""

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from supabase import Client

logger = logging.getLogger(__name__)


def list_notebook_notes(supabase: Client, notebook_id: str, user_id: str) -> List[Dict[str, Any]]:
    """Fetches all notes for a given notebook ordered by most recently updated.

    Args:
        supabase: Authenticated Supabase client instance.
        notebook_id: UUID of the notebook workspace.
        user_id: UUID of the authenticated owner.

    Returns:
        List of note dictionaries, or empty list on failure or if none exist.
    """
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
    """Fetches a single note by its unique identifier.

    Args:
        supabase: Authenticated Supabase client instance.
        note_id: UUID of the note.
        user_id: UUID of the owner.

    Returns:
        Note dictionary, or None if not found or unauthorized.
    """
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
    """Creates a new note within a notebook workspace.

    Args:
        supabase: Authenticated Supabase client instance.
        notebook_id: UUID of the parent notebook.
        user_id: UUID of the creating user.
        title: Optional title string (defaults to 'Untitled Note').
        content: Markdown body of the note.
        source_message_id: Optional UUID of a chat message the note was created from.

    Returns:
        Dictionary representation of the newly created note row.

    Raises:
        ValueError: If insertion into the database fails.
    """
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
    """Updates title and/or content of an existing note.

    Automatically sets the updated_at timestamp to the current UTC time.

    Args:
        supabase: Authenticated Supabase client instance.
        note_id: UUID of the note to update.
        user_id: UUID of the authenticated owner.
        title: Optional new title.
        content: Optional new Markdown content.

    Returns:
        Updated note dictionary, or None if not found or update failed.
    """
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
    """Deletes a note from the database.

    Args:
        supabase: Authenticated Supabase client instance.
        note_id: UUID of the note to delete.
        user_id: UUID of the authenticated owner.

    Returns:
        True if deletion succeeded; False otherwise.
    """
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
