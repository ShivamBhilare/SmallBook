import pytest
from unittest.mock import MagicMock
from uuid import uuid4

from app.services.sources.source_service import get_all_user_sources, link_sources_to_notebook
from app.routers.sources import get_library_sources


def test_get_all_user_sources():
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
            mock_in = MagicMock()
            mock_in.execute.return_value = MagicMock(data=mock_nb_data)
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
        elif table_name in ["notebook_sources", "notebooks"]:
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
