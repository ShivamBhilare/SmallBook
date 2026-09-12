"""
Source Management Service Package

Exports functions for source document lifecycle management: file upload deduplication,
cross-notebook linking, background storage persistence, and resource cleanup.
"""

from app.services.sources.source_service import (
    handle_source_upload,
    get_notebook_sources,
    get_all_user_sources,
    rename_source,
    link_sources_to_notebook,
    remove_source_from_notebook,
    delete_source_permanently,
)

__all__ = [
    "handle_source_upload",
    "get_notebook_sources",
    "get_all_user_sources",
    "rename_source",
    "link_sources_to_notebook",
    "remove_source_from_notebook",
    "delete_source_permanently",
]

