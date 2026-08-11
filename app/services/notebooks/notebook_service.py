import logging
from typing import List, Optional, Dict, Any
from supabase import Client
from postgrest.exceptions import APIError
from app.models.notebook_models import NotebookCreateSchema, NotebookUpdateSchema

logger = logging.getLogger(__name__)

# EXCEPTIONS

class NotebookServiceError(Exception):
    """Base exception for notebook-related failures."""
    pass

class DatabaseError(NotebookServiceError):
    """Raised when a database connection or query fails."""
    pass

# DATABASE SERVICES

def get_user_notebooks(supabase: Client, user_id: str) -> List[Dict[str, Any]]:
    """Fetch all notebooks owned by the current user."""
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
    """Fetch a single notebook by ID, strictly enforcing user ownership."""
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
    """Create a new notebook and return the created record."""
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
    supabase: Client, notebook_id: str, user_id: str, payload: NotebookUpdateSchema
) -> Optional[Dict[str, Any]]:
    """Update a notebook, returning the updated record or None if not found."""
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
    """Delete a notebook and return True if successful, False if not found."""
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