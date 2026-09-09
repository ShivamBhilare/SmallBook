from unittest.mock import MagicMock
from uuid import uuid4
from datetime import datetime, timezone

from app.models.study_models import NoteCreateRequest, NoteResponse
from app.services.study.note_service import (
    create_note,
    list_notebook_notes,
    update_note,
    delete_note
)


def test_note_models_validation():
    # 1. Test create schema
    req = NoteCreateRequest(title="Key Summary", content="# Main Points\n- Point 1\n- Point 2")
    assert req.title == "Key Summary"
    assert "Point 1" in req.content

    # 2. Test response schema
    note_id = uuid4()
    nb_id = uuid4()
    u_id = uuid4()
    resp = NoteResponse(
        id=note_id,
        notebook_id=nb_id,
        user_id=u_id,
        title="Key Summary",
        content="# Main Points",
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc)
    )
    assert resp.id == note_id
    assert resp.title == "Key Summary"


def test_note_service_crud():
    mock_client = MagicMock()
    mock_table = MagicMock()
    mock_client.table.return_value = mock_table

    sample_id = str(uuid4())
    sample_nb = str(uuid4())
    sample_user = str(uuid4())

    # Create Note
    mock_insert = MagicMock()
    mock_insert.execute.return_value = MagicMock(data=[{
        "id": sample_id,
        "notebook_id": sample_nb,
        "user_id": sample_user,
        "title": "Study Notes",
        "content": "Grounded notes text",
        "created_at": "2026-08-28T00:00:00Z",
        "updated_at": "2026-08-28T00:00:00Z"
    }])
    mock_table.insert.return_value = mock_insert

    note = create_note(mock_client, sample_nb, sample_user, "Study Notes", "Grounded notes text")
    assert note["id"] == sample_id
    assert note["title"] == "Study Notes"

    # List Notes
    mock_select = MagicMock()
    mock_table.select.return_value = mock_select
    mock_select.eq.return_value = mock_select
    mock_select.order.return_value = mock_select
    mock_select.execute.return_value = MagicMock(data=[note])

    notes = list_notebook_notes(mock_client, sample_nb, sample_user)
    assert len(notes) == 1
    assert notes[0]["id"] == sample_id

    # Update Note
    mock_update = MagicMock()
    mock_table.update.return_value = mock_update
    mock_update.eq.return_value = mock_update
    mock_update.execute.return_value = MagicMock(data=[{
        "id": sample_id,
        "title": "Updated Title",
        "content": "Updated content"
    }])

    updated = update_note(mock_client, sample_id, sample_user, title="Updated Title", content="Updated content")
    assert updated["title"] == "Updated Title"

    # Delete Note
    mock_delete = MagicMock()
    mock_table.delete.return_value = mock_delete
    mock_delete.eq.return_value = mock_delete
    mock_delete.execute.return_value = MagicMock(data=[{"id": sample_id}])

    deleted = delete_note(mock_client, sample_id, sample_user)
    assert deleted is True
