"""
Notebook Service Package

Exports CRUD business logic functions and service exceptions for managing
user notebook workspaces in Supabase.
"""

from app.services.notebooks.notebook_service import (
    get_user_notebooks,
    get_notebook_by_id,
    create_notebook,
    update_notebook,
    delete_notebook,
    NotebookServiceError,
    DatabaseError,
)

__all__ = [
    "get_user_notebooks",
    "get_notebook_by_id",
    "create_notebook",
    "update_notebook",
    "delete_notebook",
    "NotebookServiceError",
    "DatabaseError",
]

