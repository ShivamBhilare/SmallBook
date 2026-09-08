import os
from unittest.mock import MagicMock
from uuid import uuid4
import pytest
from fastapi import HTTPException

from app.routers.sources import rename_source, get_source_status, remove_source
from app.routers.chat import get_notebook_chat_history, clear_notebook_chat_history, send_chat_message
from app.models.source_models import SourceRenameSchema
from app.models.chat_models import ChatRequestSchema


def test_rename_source_ownership_check():
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

