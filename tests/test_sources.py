"""Source Document Management and Library Services Test Suite for SmallBook.

Validates:
- Universal Sources Library: Aggregating all uploaded PDF documents for a user with notebook cross-links.
- Library Sources endpoint: Serving library documents filtered by current workspace ownership.
- Notebook verification: Rejecting library queries with HTTP 404 when notebook is missing or unowned.
- Source detachment: Removing a source link from a notebook while preventing unauthorized deletions.
- Notebook sources lookup: Fetching all active source records linked to a specific notebook.
"""

from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from app.routers.sources import get_library_sources
from app.services.sources.source_service import get_all_user_sources


def test_get_all_user_sources():
    """Verifies that get_all_user_sources returns user documents with linked notebook titles.

    Pattern:
        - Arrange: Mock database tables for sources, notebook_sources, and notebooks.
        - Act: Call get_all_user_sources.
        - Assert: Verify two sources are returned and first source contains linked notebook metadata.
    """
    mock_client = MagicMock()
    user_id = str(uuid4())
    source_id_1 = str(uuid4())
    source_id_2 = str(uuid4())
    notebook_id_1 = str(uuid4())

    mock_sources_data = [
        {"id": source_id_1, "user_id": user_id, "original_filename": "Doc1.pdf", "file_size_bytes": 1024, "created_at": "2026-09-01T00:00:00Z"},
        {"id": source_id_2, "user_id": user_id, "original_filename": "Doc2.pdf", "file_size_bytes": 2048, "created_at": "2026-09-02T00:00:00Z"}
    ]
    mock_ns_data = [
        {"source_id": source_id_1, "notebook_id": notebook_id_1}
    ]
    mock_nb_data = [
        {"id": notebook_id_1, "title": "Math Notebook"}
    ]

    def table_side_effect(table_name):
        mock_t = MagicMock()
        if table_name == "sources":
            mock_select = MagicMock()
            mock_eq = MagicMock()
            mock_order = MagicMock()
            mock_order.execute.return_value = MagicMock(data=mock_sources_data)
            mock_eq.order.return_value = mock_order
            mock_eq.execute.return_value = MagicMock(data=mock_sources_data)
            mock_select.eq.return_value = mock_eq
            mock_t.select.return_value = mock_select
        elif table_name == "notebook_sources":
            mock_select = MagicMock()
            mock_in = MagicMock()
            mock_in.execute.return_value = MagicMock(data=mock_ns_data)
            mock_select.in_.return_value = mock_in
            mock_t.select.return_value = mock_select
        elif table_name == "notebooks":
            mock_select = MagicMock()
            mock_eq = MagicMock()
            mock_in = MagicMock()
            mock_in.execute.return_value = MagicMock(data=mock_nb_data)
            mock_eq.in_.return_value = mock_in
            mock_select.eq.return_value = mock_eq
            # Also allow direct in_ for backward compatibility
            mock_select.in_.return_value = mock_in
            mock_t.select.return_value = mock_select
        return mock_t

    mock_client.table.side_effect = table_side_effect

    sources = get_all_user_sources(mock_client, user_id)
    assert len(sources) == 2
    assert sources[0]["original_filename"] == "Doc1.pdf"
    assert len(sources[0]["notebooks"]) == 1
    assert sources[0]["notebooks"][0]["title"] == "Math Notebook"
    assert len(sources[1]["notebooks"]) == 0


def test_get_library_sources_endpoint():
    """Verifies that get_library_sources endpoint returns all accessible user sources.

    Pattern:
        - Arrange: Mock Supabase client verifying notebook ownership and returning sources list.
        - Act: Call get_library_sources.
        - Assert: Verify returned payload contains sources list with expected document name.
    """
    mock_client = MagicMock()
    mock_user = MagicMock()
    mock_user.id = str(uuid4())
    notebook_id = str(uuid4())

    mock_sources_data = [
        {"id": str(uuid4()), "user_id": mock_user.id, "original_filename": "Doc1.pdf", "file_size_bytes": 1024}
    ]

    def table_side_effect(table_name):
        mock_t = MagicMock()
        if table_name == "sources":
            mock_select = MagicMock()
            mock_eq = MagicMock()
            mock_order = MagicMock()
            mock_order.execute.return_value = MagicMock(data=mock_sources_data)
            mock_eq.order.return_value = mock_order
            mock_select.eq.return_value = mock_eq
            mock_t.select.return_value = mock_select
        elif table_name == "notebooks":
            mock_select = MagicMock()
            mock_eq1 = MagicMock()
            mock_eq2 = MagicMock()
            mock_eq2.execute.return_value = MagicMock(data=[{"id": notebook_id}])
            mock_eq1.eq.return_value = mock_eq2
            mock_eq1.execute.return_value = MagicMock(data=[{"id": notebook_id}])
            mock_select.eq.return_value = mock_eq1
            mock_in = MagicMock()
            mock_in.execute.return_value = MagicMock(data=[])
            mock_select.in_.return_value = mock_in
            mock_t.select.return_value = mock_select
        elif table_name == "notebook_sources":
            mock_select = MagicMock()
            mock_in = MagicMock()
            mock_in.execute.return_value = MagicMock(data=[])
            mock_select.in_.return_value = mock_in
            mock_t.select.return_value = mock_select
        return mock_t

    mock_client.table.side_effect = table_side_effect

    response = get_library_sources(notebook_id=notebook_id, user=mock_user, client=mock_client)
    assert "sources" in response
    assert len(response["sources"]) == 1
    assert response["sources"][0]["original_filename"] == "Doc1.pdf"


def test_get_library_sources_notebook_not_found():
    """Verifies that get_library_sources raises HTTP 404 when notebook does not exist.

    Pattern:
        - Arrange: Mock database returning empty notebook record list.
        - Act & Assert: Call get_library_sources inside pytest.raises(Exception), confirming 404.
    """
    mock_client = MagicMock()
    mock_user = MagicMock()
    mock_user.id = str(uuid4())
    notebook_id = str(uuid4())

    mock_t = MagicMock()
    mock_select = MagicMock()
    mock_eq1 = MagicMock()
    mock_eq2 = MagicMock()
    mock_eq2.execute.return_value = MagicMock(data=[])
    mock_eq1.eq.return_value = mock_eq2
    mock_select.eq.return_value = mock_eq1
    mock_t.select.return_value = mock_select
    mock_client.table.return_value = mock_t

    with pytest.raises(Exception) as exc_info:
        get_library_sources(notebook_id=notebook_id, user=mock_user, client=mock_client)
    assert "404" in str(exc_info.value) or "Notebook not found" in str(exc_info.value)


def test_remove_source_from_notebook_unauthorized():
    """Verifies that remove_source_from_notebook enforces notebook ownership.

    Pattern:
        - Arrange: Mock database returning empty list for unauthorized notebook lookup.
        - Act & Assert: Call remove_source_from_notebook inside pytest.raises(HTTPException), confirming status 404.
    """
    from fastapi import HTTPException

    from app.services.sources.source_service import remove_source_from_notebook

    mock_client = MagicMock()
    user_id = str(uuid4())
    notebook_id = str(uuid4())
    source_id = str(uuid4())

    mock_t = MagicMock()
    mock_select = MagicMock()
    mock_eq1 = MagicMock()
    mock_eq2 = MagicMock()
    mock_eq2.execute.return_value = MagicMock(data=[])  # Notebook not found or wrong user
    mock_eq1.eq.return_value = mock_eq2
    mock_select.eq.return_value = mock_eq1
    mock_t.select.return_value = mock_select
    mock_client.table.return_value = mock_t

    with pytest.raises(HTTPException) as exc_info:
        remove_source_from_notebook(mock_client, user_id, notebook_id, source_id)
    assert exc_info.value.status_code == 404


def test_remove_source_from_notebook_success():
    """Verifies successful detachment of a source from a notebook.

    Pattern:
        - Arrange: Mock authorized notebook record and successful deletion on notebook_sources table.
        - Act: Call remove_source_from_notebook.
        - Assert: Function returns True and verifies user_id and notebook_id filter conditions.
    """
    from app.services.sources.source_service import remove_source_from_notebook

    mock_client = MagicMock()
    user_id = str(uuid4())
    notebook_id = str(uuid4())
    source_id = str(uuid4())

    mock_nb_table = MagicMock()
    mock_select = MagicMock()
    mock_eq1 = MagicMock()
    mock_eq2 = MagicMock()
    mock_eq2.execute.return_value = MagicMock(data=[{"id": notebook_id}])
    mock_eq1.eq.return_value = mock_eq2
    mock_select.eq.return_value = mock_eq1
    mock_nb_table.select.return_value = mock_select

    mock_ns_table = MagicMock()
    mock_del = MagicMock()
    mock_del_eq1 = MagicMock()
    mock_del_eq2 = MagicMock()
    mock_del_eq2.execute.return_value = MagicMock(data=[])
    mock_del_eq1.eq.return_value = mock_del_eq2
    mock_del.eq.return_value = mock_del_eq1
    mock_ns_table.delete.return_value = mock_del

    def table_side_effect(name):
        if name == "notebooks":
            return mock_nb_table
        elif name == "notebook_sources":
            return mock_ns_table
        return MagicMock()

    mock_client.table.side_effect = table_side_effect

    res = remove_source_from_notebook(mock_client, user_id, notebook_id, source_id)
    assert res is True
    # Verify both id and user_id were queried
    mock_select.eq.assert_called_with("id", notebook_id)
    mock_eq1.eq.assert_called_with("user_id", user_id)


def test_get_notebook_sources_endpoint():
    """Verifies the GET /notebooks/{id}/sources API endpoint logic.

    Pattern:
        - Arrange: Mock query builder verifying notebook ownership and returning linked source rows.
        - Act: Call get_notebook_sources_endpoint.
        - Assert: Verify returned payload contains 'sources' list with matching document filename.
    """
    from app.routers.sources import get_notebook_sources_endpoint

    mock_client = MagicMock()
    user = MagicMock(id=str(uuid4()))
    notebook_id = str(uuid4())

    # Mock notebook check
    mock_nb_table = MagicMock()
    mock_select = MagicMock()
    mock_eq1 = MagicMock()
    mock_eq2 = MagicMock()
    mock_eq2.execute.return_value = MagicMock(data=[{"id": notebook_id}])
    mock_eq1.eq.return_value = mock_eq2
    mock_select.eq.return_value = mock_eq1
    mock_nb_table.select.return_value = mock_select

    # Mock notebook_sources and sources
    mock_ns_table = MagicMock()
    mock_ns_select = MagicMock()
    mock_ns_eq = MagicMock()
    mock_ns_eq.execute.return_value = MagicMock(data=[{"source_id": "src-1"}])
    mock_ns_select.eq.return_value = mock_ns_eq
    mock_ns_table.select.return_value = mock_ns_select

    mock_sources_table = MagicMock()
    mock_sources_select = MagicMock()
    mock_sources_in = MagicMock()
    mock_sources_in.execute.return_value = MagicMock(data=[{"id": "src-1", "original_filename": "Doc.pdf"}])
    mock_sources_select.in_.return_value = mock_sources_in
    mock_sources_table.select.return_value = mock_sources_select

    def table_side_effect(name):
        if name == "notebooks":
            return mock_nb_table
        elif name == "notebook_sources":
            return mock_ns_table
        elif name == "sources":
            return mock_sources_table
        return MagicMock()

    mock_client.table.side_effect = table_side_effect

    res = get_notebook_sources_endpoint(notebook_id, user, mock_client)
    assert "sources" in res
    assert len(res["sources"]) == 1
    assert res["sources"][0]["original_filename"] == "Doc.pdf"
