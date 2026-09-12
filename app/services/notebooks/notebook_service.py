"""
Notebook Workspace Data Access & Business Service

Manages database persistence, lifecycle operations, and source count aggregations
for user notebook workspaces stored in Supabase PostgreSQL tables.
Enforces user ownership filters and converts PostgREST API errors into typed
domain service exceptions.
"""

import logging
from typing import List, Optional, Dict, Any
from supabase import Client
from postgrest.exceptions import APIError
from app.models.notebook_models import NotebookCreateSchema, NotebookUpdateSchema

logger = logging.getLogger(__name__)


# =========================================================================
# 1. DOMAIN SERVICE EXCEPTIONS
# =========================================================================

class NotebookServiceError(Exception):
    """Base exception for all notebook workspace service layer failures."""
    pass


class DatabaseError(NotebookServiceError):
    """Raised when a Supabase PostgreSQL query or connection execution fails."""
    pass


# =========================================================================
# 2. NOTEBOOK WORKSPACE CRUD OPERATIONS
# =========================================================================

def get_user_notebooks(supabase: Client, user_id: str) -> List[Dict[str, Any]]:
    """
    Fetches all notebook workspaces owned by the specified user.

    Retrieves notebooks ordered chronologically by `updated_at` descending,
    and performs a secondary batch query on `notebook_sources` to annotate
    each notebook record with its active linked source document count (`sources_count`).

    Args:
        supabase: Scoped or service Supabase client.
        user_id: Unique UUID string of the requesting user.

    Returns:
        List[Dict[str, Any]]: List of notebook dictionaries with `sources_count` attached.

    Raises:
        DatabaseError: If the PostgREST query fails or an unexpected exception occurs.
    """
    try:
        response = (
            supabase.table("notebooks")
            .select("*")
            .eq("user_id", user_id)
            .order("updated_at", desc=True)
            .execute()
        )
        notebooks = response.data if response.data else []
        if not notebooks:
            return []

        try:
            nb_ids = [n["id"] for n in notebooks]
            ns_res = supabase.table("notebook_sources").select("notebook_id").in_("notebook_id", nb_ids).execute()
            ns_data = ns_res.data or []
            
            counts = {}
            for row in ns_data:
                nid = row["notebook_id"]
                counts[nid] = counts.get(nid, 0) + 1

            for n in notebooks:
                n["sources_count"] = counts.get(n["id"], 0)
        except Exception as count_err:
            logger.warning(f"Error fetching notebook source counts: {count_err}")

        return notebooks
        
    except APIError as e:
        logger.error(f"Supabase API error fetching notebooks for user {user_id}: {e}")
        raise DatabaseError("Database failed to fetch notebooks.") from e
    except Exception as e:
        logger.exception(f"Unexpected system error fetching notebooks for user {user_id}")
        raise DatabaseError("An unexpected error occurred while fetching notebooks.") from e


def get_notebook_by_id(supabase: Client, notebook_id: str, user_id: str) -> Optional[Dict[str, Any]]:
    """
    Fetches a single notebook workspace by ID, strictly enforcing user ownership.

    Args:
        supabase: Scoped or service Supabase client.
        notebook_id: UUID string of the target notebook.
        user_id: UUID string of the expected owner.

    Returns:
        Optional[Dict[str, Any]]: Notebook record dictionary if found and owned, else None.

    Raises:
        DatabaseError: If database communication fails.
    """
    try:
        response = (
            supabase.table("notebooks")
            .select("*")
            .eq("id", notebook_id)
            .eq("user_id", user_id)
            .execute()
        )
        if not response.data:
            return None
        return response.data[0]
        
    except APIError as e:
        logger.error(f"Supabase API error fetching notebook {notebook_id} for user {user_id}: {e}")
        raise DatabaseError(f"Database failed to fetch notebook {notebook_id}.") from e
    except Exception as e:
        logger.exception(f"Unexpected error fetching notebook {notebook_id}")
        raise DatabaseError("An unexpected error occurred.") from e


def create_notebook(supabase: Client, user_id: str, payload: NotebookCreateSchema) -> Dict[str, Any]:
    """
    Creates a new notebook workspace record for the user.

    Dumps the schema excluding None values so default schema values (e.g. title
    "Untitled SmallBook") are written cleanly to the PostgreSQL record.

    Args:
        supabase: Scoped or service Supabase client.
        user_id: UUID string of the creating user.
        payload: Validated notebook creation schema.

    Returns:
        Dict[str, Any]: Newly inserted notebook database record.

    Raises:
        DatabaseError: If insert fails or returns an empty payload.
    """
    try:
        # exclude_none=True ensures the default "Untitled SmallBook" is passed to DB
        data = payload.model_dump(exclude_none=True)
        data["user_id"] = user_id

        response = supabase.table("notebooks").insert(data).execute()
        
        if not response.data:
            logger.error(f"Notebook created but no data returned for user {user_id}.")
            raise DatabaseError("Notebook created, but response was empty.")
            
        return response.data[0]
        
    except APIError as e:
        logger.error(f"Supabase API error creating notebook for user {user_id}: {e}")
        raise DatabaseError("Database failed to create notebook.") from e
    except Exception as e:
        logger.exception(f"Unexpected error creating notebook for user {user_id}")
        raise DatabaseError("An unexpected error occurred during creation.") from e


def update_notebook(
    supabase: Client,
    notebook_id: str,
    user_id: str,
    payload: NotebookUpdateSchema
) -> Optional[Dict[str, Any]]:
    """
    Updates an existing notebook workspace's metadata.

    Uses `exclude_unset=True` to only update fields explicitly provided by the caller.
    If no fields were supplied in the update payload, short-circuits to avoid a no-op DB write.

    Args:
        supabase: Scoped or service Supabase client.
        notebook_id: UUID string of the target notebook.
        user_id: UUID string of the authenticated owner.
        payload: Validated notebook update schema.

    Returns:
        Optional[Dict[str, Any]]: The updated notebook record dictionary, or None if not found.

    Raises:
        DatabaseError: If database update fails.
    """
    try:
        # exclude_unset=True ensures we only update fields the user explicitly sent
        data = payload.model_dump(exclude_unset=True)
        
        # Short-circuit if there are no actual updates to make (e.g. empty PATCH request)
        if not data:
            logger.info(f"No update data provided for notebook {notebook_id}. Returning existing.")
            return get_notebook_by_id(supabase, notebook_id, user_id)

        response = (
            supabase.table("notebooks")
            .update(data)
            .eq("id", notebook_id)
            .eq("user_id", user_id)
            .execute()
        )
        
        if not response.data:
            return None
        return response.data[0]
        
    except APIError as e:
        logger.error(f"Supabase API error updating notebook {notebook_id}: {e}")
        raise DatabaseError("Database failed to update notebook.") from e
    except Exception as e:
        logger.exception(f"Unexpected error updating notebook {notebook_id}")
        raise DatabaseError("An unexpected error occurred during update.") from e


def delete_notebook(supabase: Client, notebook_id: str, user_id: str) -> bool:
    """
    Deletes a notebook workspace owned by the user.

    Foreign key constraints with ON DELETE CASCADE in PostgreSQL automatically
    clean up associated chat messages, notebook_sources references, and study records.

    Args:
        supabase: Scoped or service Supabase client.
        notebook_id: UUID string of the target notebook.
        user_id: UUID string of the owner.

    Returns:
        bool: True if a record was successfully deleted, False if no matching record existed.

    Raises:
        DatabaseError: If database delete command fails.
    """
    try:
        response = (
            supabase.table("notebooks")
            .delete()
            .eq("id", notebook_id)
            .eq("user_id", user_id)
            .execute()
        )
        return bool(response.data)
        
    except APIError as e:
        logger.error(f"Supabase API error deleting notebook {notebook_id}: {e}")
        raise DatabaseError("Database failed to delete notebook.") from e
    except Exception as e:
        logger.exception(f"Unexpected error deleting notebook {notebook_id}")
        raise DatabaseError("An unexpected error occurred during deletion.") from e