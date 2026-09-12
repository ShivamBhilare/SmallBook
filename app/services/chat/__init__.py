"""Chat Services Package.

Provides high-level business logic and database persistence routines for
notebook chat sessions, message histories, model provider inference, and
grounding citation linkages.
"""

from app.services.chat.chat_service import (
    infer_llm_provider,
    save_chat_message,
    save_citations,
    get_chat_history,
    clear_chat_history
)

__all__ = [
    "infer_llm_provider",
    "save_chat_message",
    "save_citations",
    "get_chat_history",
    "clear_chat_history"
]

