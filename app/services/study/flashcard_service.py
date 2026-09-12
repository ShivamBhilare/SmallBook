"""Flashcard Persistence & Management Service.

Provides CRUD routines for user flashcard sets and individual study cards in Supabase,
including card aggregation and chunk foreign-key validation.
"""

import logging
from typing import Any, Dict, List, Optional

from supabase import Client

from app.models.study_models import FlashcardSetGenerateSchema

logger = logging.getLogger(__name__)


def list_notebook_flashcard_sets(supabase: Client, notebook_id: str, user_id: str) -> List[Dict[str, Any]]:
    """Fetches all flashcard sets for a given notebook with computed card counts.

    Queries flashcard sets owned by the user in descending chronological order
    and batches card counts across all matching set IDs.

    Args:
        supabase: Authenticated Supabase client instance.
        notebook_id: UUID of the workspace notebook.
        user_id: UUID of the authenticated owner.

    Returns:
        List of flashcard set dictionaries with an attached 'cards_count' integer.
    """
    try:
        res = (
            supabase.table("flashcard_sets")
            .select("id, notebook_id, user_id, source_id, title, custom_prompt, created_at, updated_at")
            .eq("notebook_id", notebook_id)
            .eq("user_id", user_id)
            .order("created_at", desc=True)
            .execute()
        )
        sets = res.data or []
        if not sets:
            return []

        # Count cards per set in a single aggregated batch
        set_ids = [s["id"] for s in sets]
        cards_res = (
            supabase.table("flashcards")
            .select("set_id")
            .in_("set_id", set_ids)
            .execute()
        )
        cards_data = cards_res.data or []
        counts = {}
        for c in cards_data:
            sid = c["set_id"]
            counts[sid] = counts.get(sid, 0) + 1

        for s in sets:
            s["cards_count"] = counts.get(s["id"], 0)

        return sets
    except Exception as e:
        logger.error(f"Error fetching flashcard sets for notebook {notebook_id}: {e}")
        return []


def get_flashcard_set_with_cards(supabase: Client, set_id: str, user_id: str) -> Optional[Dict[str, Any]]:
    """Fetches a specific flashcard deck and all its child cards in sequential order.

    Args:
        supabase: Authenticated Supabase client instance.
        set_id: UUID of the target flashcard set.
        user_id: UUID of the requesting owner.

    Returns:
        Deck dictionary containing populated 'cards' list and 'cards_count',
        or None if not found or unauthorized.
    """
    try:
        set_res = (
            supabase.table("flashcard_sets")
            .select("*")
            .eq("id", set_id)
            .eq("user_id", user_id)
            .execute()
        )
        if not set_res.data:
            return None
        deck = set_res.data[0]

        cards_res = (
            supabase.table("flashcards")
            .select("*")
            .eq("set_id", set_id)
            .order("order_index", desc=False)
            .execute()
        )
        deck["cards"] = cards_res.data or []
        deck["cards_count"] = len(deck["cards"])
        return deck
    except Exception as e:
        logger.error(f"Error fetching flashcard deck {set_id}: {e}")
        return None


def save_generated_flashcard_set(
    supabase: Client,
    notebook_id: str,
    user_id: str,
    source_id: str,
    custom_prompt: Optional[str],
    deck_data: FlashcardSetGenerateSchema
) -> Dict[str, Any]:
    """Persists a newly generated flashcard set and its individual cards to Supabase.

    Inserts the parent flashcard_sets row, validates referenced source chunk IDs
    against the document_chunks table to avoid foreign-key violations, and batch-inserts
    the individual child flashcard rows.

    Args:
        supabase: Authenticated or service-role Supabase client instance.
        notebook_id: UUID of the notebook workspace.
        user_id: UUID of the deck owner.
        source_id: UUID of the document source the deck was generated from.
        custom_prompt: Optional user instructions used during generation.
        deck_data: Validated flashcard set schema containing title and card items.

    Returns:
        Created flashcard set dictionary including attached 'cards' and 'cards_count'.

    Raises:
        RuntimeError: If inserting the parent flashcard set record fails.
    """
    # 1. Insert Set
    set_payload = {
        "notebook_id": notebook_id,
        "user_id": user_id,
        "source_id": source_id,
        "title": deck_data.title,
        "custom_prompt": custom_prompt
    }
    set_res = supabase.table("flashcard_sets").insert(set_payload).execute()
    if not set_res.data:
        raise RuntimeError("Failed to create flashcard set record.")
    created_set = set_res.data[0]
    set_id = created_set["id"]

    # 2. Fetch valid chunk IDs for this source to ensure foreign key safety
    valid_chunk_ids = set()
    try:
        chunks_res = supabase.table("document_chunks").select("id").eq("source_id", source_id).execute()
        if chunks_res.data:
            valid_chunk_ids = {str(c["id"]) for c in chunks_res.data}
    except Exception as e:
        logger.warning(f"Could not verify chunk IDs for source {source_id}: {e}")

    # 3. Insert Cards in batch
    cards_payload = []
    for idx, card in enumerate(deck_data.cards):
        raw_chunk_id = str(card.source_chunk_id) if card.source_chunk_id else None
        safe_chunk_id = raw_chunk_id if (raw_chunk_id and raw_chunk_id in valid_chunk_ids) else None

        cards_payload.append({
            "set_id": set_id,
            "order_index": idx,
            "front_text": card.front_text,
            "back_text": card.back_text,
            "source_chunk_id": safe_chunk_id
        })

    if cards_payload:
        cards_res = supabase.table("flashcards").insert(cards_payload).execute()
        created_set["cards"] = cards_res.data or []
        created_set["cards_count"] = len(created_set["cards"])
    else:
        created_set["cards"] = []
        created_set["cards_count"] = 0

    return created_set


def delete_flashcard_set(supabase: Client, set_id: str, user_id: str) -> bool:
    """Deletes a flashcard set and its associated cards via foreign key cascade.

    Args:
        supabase: Authenticated Supabase client instance.
        set_id: UUID of the flashcard set to delete.
        user_id: UUID of the authenticated owner.

    Returns:
        True if deletion succeeded; False otherwise.
    """
    try:
        res = (
            supabase.table("flashcard_sets")
            .delete()
            .eq("id", set_id)
            .eq("user_id", user_id)
            .execute()
        )
        return bool(res.data)
    except Exception as e:
        logger.error(f"Error deleting flashcard set {set_id}: {e}")
        return False
