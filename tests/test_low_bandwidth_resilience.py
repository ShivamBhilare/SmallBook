"""Low Bandwidth and Timeout Resilience Test Suite for SmallBook.

Validates:
- Qdrant batch upsert retries and exponential backoff upon network timeout/failure.
- Source status endpoint returning error messages, page counts, and filenames.
- Source retry service resetting jobs to queued and re-triggering ingestion.
- Study tool database persistence retry helper handling transient drops.
"""

from unittest.mock import MagicMock, patch
from uuid import uuid4
import numpy as np
import pytest

from app.services.ingestion.qdrant_db import QdrantManager
from app.services.ingestion.chunker import ChildChunk
from app.services.sources.source_service import retry_source_ingestion
from app.services.study.celery_tasks import _save_with_retry
from app.routers.sources import get_source_status


def test_qdrant_timeout_and_retries_success_on_retry():
    """Verifies QdrantManager.embed_and_upsert retries on transient timeout and succeeds."""
    import app.services.ingestion.qdrant_db as qdrant_module
    qdrant_module._qdrant_client = None

    with patch("app.services.ingestion.qdrant_db.QdrantClient") as mock_client_cls, \
         patch("app.services.ingestion.qdrant_db.get_embedding_model") as mock_model_getter, \
         patch("time.sleep") as mock_sleep:
        
        mock_client = MagicMock()
        mock_client_cls.return_value = mock_client
        mock_client.collection_exists.return_value = True
        
        mock_embedder = MagicMock()
        mock_embedder.encode.return_value = np.array([[0.1] * 768])
        mock_model_getter.return_value = mock_embedder

        service = QdrantManager()

        # Simulate: 1st upsert fails with timeout, 2nd succeeds
        mock_client.upsert.side_effect = [
            Exception("WriteTimeout('The write operation timed out')"),
            MagicMock()
        ]

        children = [
            ChildChunk(
                id=str(uuid4()),
                parent_id=str(uuid4()),
                source_id="doc-123",
                text="Sample chunk text for embedding.",
                order=0
            )
        ]
        service.embed_and_upsert(children)

        assert mock_client.upsert.call_count == 2
        mock_sleep.assert_called_once_with(1.5)


def test_qdrant_timeout_exhausted_raises_exception():
    """Verifies QdrantManager.embed_and_upsert raises after max retries are exhausted."""
    import app.services.ingestion.qdrant_db as qdrant_module
    qdrant_module._qdrant_client = None

    with patch("app.services.ingestion.qdrant_db.QdrantClient") as mock_client_cls, \
         patch("app.services.ingestion.qdrant_db.get_embedding_model") as mock_model_getter, \
         patch("time.sleep"):
        
        mock_client = MagicMock()
        mock_client_cls.return_value = mock_client
        mock_client.collection_exists.return_value = True
        
        mock_embedder = MagicMock()
        mock_embedder.encode.return_value = np.array([[0.1] * 768])
        mock_model_getter.return_value = mock_embedder

        service = QdrantManager()

        # All 3 attempts fail
        def raise_timeout(*args, **kwargs):
            raise Exception("ReadTimeout('The read operation timed out')")
        mock_client.upsert.side_effect = raise_timeout

        children = [
            ChildChunk(
                id=str(uuid4()),
                parent_id=str(uuid4()),
                source_id="doc-123",
                text="Sample chunk text for embedding.",
                order=0
            )
        ]
        with pytest.raises(Exception) as exc_info:
            service.embed_and_upsert(children)

        assert "ReadTimeout" in str(exc_info.value)
        assert mock_client.upsert.call_count == 3


def test_retry_source_ingestion_service():
    """Verifies retry_source_ingestion resets source and job status and triggers Celery."""
    mock_client = MagicMock()
    user_id = str(uuid4())
    notebook_id = str(uuid4())
    source_id = str(uuid4())

    # Mock source query
    mock_src_table = MagicMock()
    mock_src_select = MagicMock()
    mock_src_select.eq.return_value.eq.return_value.execute.return_value = MagicMock(
        data=[{"id": source_id, "user_id": user_id, "storage_path": "path/file.pdf"}]
    )
    mock_src_table.select.return_value = mock_src_select
    mock_src_table.update.return_value.eq.return_value.execute.return_value = MagicMock()

    # Mock job query
    mock_job_table = MagicMock()
    mock_job_select = MagicMock()
    mock_job_select.eq.return_value.execute.return_value = MagicMock(
        data=[{"id": str(uuid4()), "source_id": source_id, "status": "failed"}]
    )
    mock_job_table.select.return_value = mock_job_select
    mock_job_table.update.return_value.eq.return_value.execute.return_value = MagicMock()

    def table_side_effect(name):
        if name == "sources":
            return mock_src_table
        if name == "ingestion_jobs":
            return mock_job_table
        return MagicMock()

    mock_client.table.side_effect = table_side_effect

    with patch("app.services.ingestion.celery_tasks.process_pdf_task.apply_async") as mock_celery:
        result = retry_source_ingestion(mock_client, user_id, notebook_id, source_id)

        assert result["status"] == "queued"
        assert result["source_id"] == source_id
        mock_celery.assert_called_once()


def test_get_source_status_returns_error_and_page_count():
    """Verifies get_source_status returns error_message and page_count from sources and jobs."""
    mock_client = MagicMock()
    mock_user = MagicMock()
    mock_user.id = str(uuid4())
    notebook_id = str(uuid4())
    source_id = str(uuid4())

    # Mock notebooks table
    mock_nb_table = MagicMock()
    mock_nb_table.select.return_value.eq.return_value.eq.return_value.execute.return_value = MagicMock(
        data=[{"id": notebook_id, "user_id": mock_user.id}]
    )

    # Mock sources table
    mock_src_table = MagicMock()
    mock_src_table.select.return_value.eq.return_value.eq.return_value.execute.return_value = MagicMock(
        data=[{
            "id": source_id,
            "original_filename": "lecture.pdf",
            "page_count": 12,
            "ingestion_status": "failed",
            "ingestion_error": "WriteTimeout during vector upsert"
        }]
    )

    # Mock jobs table
    mock_job_table = MagicMock()
    mock_job_table.select.return_value.eq.return_value.execute.return_value = MagicMock(
        data=[{
            "id": str(uuid4()),
            "status": "failed",
            "error_message": "WriteTimeout during vector upsert"
        }]
    )

    def table_side_effect(name):
        if name == "notebooks":
            return mock_nb_table
        if name == "sources":
            return mock_src_table
        if name == "ingestion_jobs":
            return mock_job_table
        return MagicMock()

    mock_client.table.side_effect = table_side_effect

    result = get_source_status(notebook_id, source_id, user=mock_user, client=mock_client)

    assert result["status"] == "failed"
    assert result["filename"] == "lecture.pdf"
    assert result["page_count"] == 12
    assert "WriteTimeout" in result["error_message"]


def test_study_save_with_retry_succeeds_on_transient_failure():
    """Verifies _save_with_retry retries on database connectivity exceptions."""
    mock_func = MagicMock()
    mock_func.side_effect = [
        RuntimeError("Connection closed by peer"),
        {"id": "deck-456", "title": "Math Quiz"}
    ]

    with patch("time.sleep") as mock_sleep:
        res = _save_with_retry(mock_func, max_attempts=3)
        assert res["id"] == "deck-456"
        assert mock_func.call_count == 2
        mock_sleep.assert_called_once_with(2)
