"""Security Ownership Boundary and Environment Configuration Tests for SmallBook.

Validates:
- Multi-tenant data isolation: Endpoints reject requests with HTTP 404 when a user attempts
  to access, rename, poll, or delete sources belonging to another user's notebook.
- Chat route isolation: Reading, clearing, or posting to conversation history verifies notebook ownership.
- Environment documentation: .env.example contains all critical production environment keys.
"""

import os
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from fastapi import HTTPException

from app.models.chat_models import ChatRequestSchema
from app.models.source_models import SourceRenameSchema
from app.routers.chat import (
    clear_notebook_chat_history,
    get_notebook_chat_history,
    send_chat_message,
)
from app.routers.sources import get_source_status, remove_source, rename_source


def test_rename_source_ownership_check():
    """Verifies that attempting to rename a source in an unowned notebook raises HTTP 404.

    Pattern:
        - Arrange: Mock Supabase query returning empty data (user does not own notebook).
        - Act & Assert: Call rename_source inside pytest.raises(HTTPException), verifying status 404.
    """
    mock_client = MagicMock()
    mock_user = MagicMock()
    mock_user.id = str(uuid4())
    notebook_id = str(uuid4())
    source_id = str(uuid4())

    mock_t = MagicMock()
    mock_select = MagicMock()
    mock_eq1 = MagicMock()
    mock_eq2 = MagicMock()
    mock_eq2.execute.return_value = MagicMock(data=[])  # Notebook not owned by user
    mock_eq1.eq.return_value = mock_eq2
    mock_select.eq.return_value = mock_eq1
    mock_t.select.return_value = mock_select
    mock_client.table.return_value = mock_t

    payload = SourceRenameSchema(filename="renamed.pdf")
    with pytest.raises(HTTPException) as exc_info:
        rename_source(notebook_id, source_id, payload, user=mock_user, client=mock_client)
    assert exc_info.value.status_code == 404


def test_get_source_status_ownership_check():
    """Verifies that querying ingestion status for an unowned notebook raises HTTP 404.

    Pattern:
        - Arrange: Mock Supabase query returning empty data (unauthorized user).
        - Act & Assert: Call get_source_status inside pytest.raises(HTTPException), verifying status 404.
    """
    mock_client = MagicMock()
    mock_user = MagicMock()
    mock_user.id = str(uuid4())
    notebook_id = str(uuid4())
    source_id = str(uuid4())

    mock_t = MagicMock()
    mock_select = MagicMock()
    mock_eq1 = MagicMock()
    mock_eq2 = MagicMock()
    mock_eq2.execute.return_value = MagicMock(data=[])  # Notebook not owned by user
    mock_eq1.eq.return_value = mock_eq2
    mock_select.eq.return_value = mock_eq1
    mock_t.select.return_value = mock_select
    mock_client.table.return_value = mock_t

    with pytest.raises(HTTPException) as exc_info:
        get_source_status(notebook_id, source_id, user=mock_user, client=mock_client)
    assert exc_info.value.status_code == 404


def test_remove_source_ownership_check():
    """Verifies that attempting to remove or detach a source from an unowned notebook raises HTTP 404.

    Pattern:
        - Arrange: Mock Supabase query returning empty data for notebook ownership lookup.
        - Act & Assert: Call remove_source inside pytest.raises(HTTPException), verifying status 404.
    """
    mock_client = MagicMock()
    mock_user = MagicMock()
    mock_user.id = str(uuid4())
    notebook_id = str(uuid4())
    source_id = str(uuid4())
    mock_bg = MagicMock()

    mock_t = MagicMock()
    mock_select = MagicMock()
    mock_eq1 = MagicMock()
    mock_eq2 = MagicMock()
    mock_eq2.execute.return_value = MagicMock(data=[])  # Notebook not owned by user
    mock_eq1.eq.return_value = mock_eq2
    mock_select.eq.return_value = mock_eq1
    mock_t.select.return_value = mock_select
    mock_client.table.return_value = mock_t

    with pytest.raises(HTTPException) as exc_info:
        remove_source(notebook_id, source_id, background_tasks=mock_bg, mode="notebook", user=mock_user, client=mock_client)
    assert exc_info.value.status_code == 404


def test_chat_routes_notebook_ownership():
    """Verifies that history fetch, clear, and message submission all enforce notebook ownership.

    Pattern:
        - Arrange: Mock Supabase query returning empty data (unauthorized user).
        - Act & Assert:
            1. get_notebook_chat_history raises 404.
            2. clear_notebook_chat_history raises 404.
            3. send_chat_message raises 404.
    """
    mock_client = MagicMock()
    mock_user = MagicMock()
    mock_user.id = str(uuid4())
    notebook_id = str(uuid4())

    mock_t = MagicMock()
    mock_select = MagicMock()
    mock_eq1 = MagicMock()
    mock_eq2 = MagicMock()
    mock_eq2.execute.return_value = MagicMock(data=[])  # Notebook not found or wrong user
    mock_eq1.eq.return_value = mock_eq2
    mock_select.eq.return_value = mock_eq1
    mock_t.select.return_value = mock_select
    mock_client.table.return_value = mock_t

    # 1. get_notebook_chat_history
    with pytest.raises(HTTPException) as exc_info:
        get_notebook_chat_history(notebook_id, user=mock_user, client=mock_client)
    assert exc_info.value.status_code == 404

    # 2. clear_notebook_chat_history
    with pytest.raises(HTTPException) as exc_info:
        clear_notebook_chat_history(notebook_id, user=mock_user, client=mock_client)
    assert exc_info.value.status_code == 404

    # 3. send_chat_message
    with pytest.raises(HTTPException) as exc_info:
        send_chat_message(notebook_id, ChatRequestSchema(query="hello"), user=mock_user, client=mock_client)
    assert exc_info.value.status_code == 404


def test_env_example_contains_all_critical_keys():
    """Verifies that .env.example contains all required environment variables for deployment.

    Pattern:
        - Arrange: Read `.env.example` from repository root.
        - Act: Verify presence of all required security, database, vector, and API keys.
        - Assert: All required keys exist in file content.
    """
    env_example_path = os.path.join(os.path.dirname(__file__), "..", ".env.example")
    assert os.path.exists(env_example_path)
    
    with open(env_example_path, "r", encoding="utf-8") as f:
        content = f.read()

    required_keys = [
        "SUPABASE_URL",
        "SUPABASE_ANON_KEY",
        "SUPABASE_KEY",
        "DATABASE_URL",
        "SUPABASE_SERVICE_ROLE_KEY",
        "QDRANT_URL",
        "QDRANT_API_KEY",
        "HF_TOKEN",
        "REDIS_URL",
        "APP_ENCRYPTION_KEY",
        "GEMINI_API_KEY",
        "GROQ_API_KEY"
    ]
    for key in required_keys:
        assert key in content, f"Missing {key} in .env.example"
