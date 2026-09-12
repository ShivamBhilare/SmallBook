"""Concurrency, Connection Pooling, and Performance Batching Tests for SmallBook.

Validates:
- Redis client singleton lifecycle and connection pool reuse across application threads.
- Offline circuit breaker backoff: Fast-fails for 10s interval to eliminate socket blocking.
- Distributed concurrency locks and cooldown keys via Redis SET NX/EX.
- In-memory thread-safe fallback for distributed locks when Redis is unreachable.
- Celery ingestion chunk batching: Verifies parent chunks are partitioned into batches
  of 250 records to prevent HTTP POST payload size exhaustion against Supabase REST API.
"""

import sys
import time
from unittest.mock import MagicMock, patch
from uuid import uuid4

# Mock heavy ML framework for fast unit testing
if "sentence_transformers" not in sys.modules:
    sys.modules["sentence_transformers"] = MagicMock()

from app.core.redis_client import (
    _OFFLINE_RETRY_INTERVAL,
    get_redis_client,
    reset_redis_client,
)
from app.services.study.concurrency import (
    _local_cooldowns,
    _local_locks,
    acquire_study_lock,
    check_and_set_cooldown,
    clear_cooldown,
    release_study_lock,
)


def test_redis_client_singleton():
    """Verifies get_redis_client returns a singleton instance and reuses the connection pool.

    Pattern:
        - Arrange: Reset existing singleton, mock Redis and ConnectionPool factory.
        - Act: Fetch client twice, reset, then fetch a third time.
        - Assert: First two clients are identical instances (factory called once);
          third call creates new instance (factory called twice).
    """
    reset_redis_client()
    mock_redis = MagicMock()
    mock_redis.ping.return_value = True

    with patch("redis.Redis", return_value=mock_redis), \
         patch("redis.ConnectionPool.from_url") as mock_pool_factory:
        mock_pool = MagicMock()
        mock_pool_factory.return_value = mock_pool

        client_1 = get_redis_client()
        client_2 = get_redis_client()

        # Both calls must return the same singleton object
        assert client_1 is client_2
        # ConnectionPool and Redis should only be instantiated once
        assert mock_pool_factory.call_count == 1

        # Resetting client should close connection and allow recreation
        reset_redis_client()
        client_3 = get_redis_client()
        assert client_3 is not None
        assert mock_pool_factory.call_count == 2

    reset_redis_client()


def test_redis_client_offline_backoff():
    """Verifies that offline Redis failure is cached for _OFFLINE_RETRY_INTERVAL to fast-fail.

    Pattern:
        - Arrange: Mock Redis ping raising ConnectionError.
        - Act & Assert:
            1. First call fails and records offline timestamp.
            2. Immediate second call fast-fails without issuing another ping() call.
            3. Fast-forwarding past retry interval re-attempts connection and calls ping().
    """
    reset_redis_client()

    with patch("redis.Redis") as mock_redis_class:
        mock_redis_instance = MagicMock()
        mock_redis_instance.ping.side_effect = ConnectionError("Connection refused")
        mock_redis_class.return_value = mock_redis_instance

        # 1. First call fails and records offline timestamp
        t0 = time.time()
        client_1 = get_redis_client()
        assert client_1 is None
        assert mock_redis_instance.ping.call_count == 1

        # 2. Immediate second call should fast-fail without calling ping() again
        client_2 = get_redis_client()
        assert client_2 is None
        assert mock_redis_instance.ping.call_count == 1  # Not incremented!

        # 3. Fast-forward past the backoff interval -> should attempt reconnection
        with patch("app.core.redis_client.time.time", return_value=t0 + _OFFLINE_RETRY_INTERVAL + 1.0):
            client_3 = get_redis_client()
            assert client_3 is None
            assert mock_redis_instance.ping.call_count == 2  # Re-attempted!

    reset_redis_client()


def test_study_concurrency_with_pooled_redis():
    """Verifies study tool concurrency locks and cooldown keys use the pooled Redis client.

    Pattern:
        - Arrange: Mock Redis client with set, delete, and ttl operations.
        - Act & Assert:
            1. Acquire lock: Verify redis.set called with NX and EX flags.
            2. Release lock: Verify redis.delete called on lock key.
            3. Set cooldown: Verify redis.set called on cooldown key with expiration.
            4. Clear cooldown: Verify redis.delete called on cooldown key.
    """
    mock_client = MagicMock()
    mock_client.set.return_value = True
    mock_client.ttl.return_value = -2  # Key doesn't exist yet

    user_id = f"test-user-{uuid4()}"

    with patch("app.services.study.concurrency.get_redis_client", return_value=mock_client):
        # 1. Acquire lock
        acquired = acquire_study_lock(user_id, timeout_seconds=120)
        assert acquired is True
        mock_client.set.assert_called_with(f"lock:study_gen:{user_id}", "active", nx=True, ex=120)

        # 2. Release lock
        release_study_lock(user_id)
        mock_client.delete.assert_called_with(f"lock:study_gen:{user_id}")

        # 3. Check and set cooldown
        can_gen, rem = check_and_set_cooldown(user_id, "flashcards", cooldown_seconds=1800)
        assert can_gen is True
        assert rem == 0
        mock_client.set.assert_called_with(f"cooldown:study:flashcards:{user_id}", "active", ex=1800)

        # 4. Clear cooldown
        clear_cooldown(user_id, "flashcards")
        mock_client.delete.assert_called_with(f"cooldown:study:flashcards:{user_id}")


def test_study_concurrency_offline_fallback():
    """Verifies study tool concurrency seamlessly falls back to in-memory state when Redis is offline.

    Pattern:
        - Arrange: Mock get_redis_client returning None; clear user from local sets.
        - Act & Assert:
            1. Memory lock: Acquire succeeds once, second attempt fails, release allows re-acquisition.
            2. Memory cooldown: Initial attempt succeeds, immediate repeat is blocked with remaining seconds.
    """
    user_id = f"offline-user-{uuid4()}"
    _local_locks.discard(user_id)
    _local_cooldowns.pop(f"quiz:{user_id}", None)

    with patch("app.services.study.concurrency.get_redis_client", return_value=None):
        # 1. Lock in memory
        assert acquire_study_lock(user_id) is True
        assert acquire_study_lock(user_id) is False
        release_study_lock(user_id)
        assert acquire_study_lock(user_id) is True
        release_study_lock(user_id)

        # 2. Cooldown in memory
        can_gen, rem = check_and_set_cooldown(user_id, "quiz", cooldown_seconds=600)
        assert can_gen is True
        assert rem == 0

        # Immediate repeat should be blocked by cooldown
        can_gen_2, rem_2 = check_and_set_cooldown(user_id, "quiz", cooldown_seconds=600)
        assert can_gen_2 is False
        assert rem_2 > 0

        clear_cooldown(user_id, "quiz")


def test_celery_task_chunk_batching():
    """Verifies that parent chunks are inserted in batches of 250 to prevent HTTP payload overflow.

    Pattern:
        - Arrange: Generate 650 dummy parent chunks, mock Supabase database operations, and intercept chunk inserts.
        - Act: Execute process_pdf_task.run() directly without Celery broker.
        - Assert: Verify 650 chunks produce exactly 3 batches of size 250, 250, 150,
          and maintain ordered chunk_index assignments from 0 to 649.
    """
    from app.models.ingestion_models import ChildChunk, ParentChunk
    from app.services.ingestion.celery_tasks import process_pdf_task

    source_id = str(uuid4())
    storage_path = f"test/{source_id}.pdf"

    # Create 650 dummy parent chunks
    dummy_parents = [
        ParentChunk(
            id=str(uuid4()),
            notebook_id="pending",
            document_id=source_id,
            text=f"Chunk content {i}",
            order=i
        )
        for i in range(650)
    ]
    dummy_children = [
        ChildChunk(
            id=str(uuid4()),
            parent_id=dummy_parents[0].id,
            source_id=source_id,
            text="Child 1",
            order=0
        )
    ]

    mock_supabase = MagicMock()
    mock_storage = MagicMock()
    mock_storage.download.return_value = b"%PDF-1.4 dummy pdf bytes"
    mock_supabase.storage.from_.return_value = mock_storage

    user_id = str(uuid4())

    # Capture all insert calls to document_chunks
    inserted_batches = []
    def table_mock(table_name):
        mock_t = MagicMock()
        if table_name == "document_chunks":
            def insert_mock(records):
                inserted_batches.append(records)
                return MagicMock(execute=MagicMock())
            mock_t.insert.side_effect = insert_mock
        elif table_name == "sources":
            mock_t.select.return_value.eq.return_value.execute.return_value = MagicMock(
                data=[{"id": source_id, "storage_path": storage_path}]
            )
            mock_t.update.return_value.eq.return_value.execute.return_value = MagicMock()
        else:
            mock_t.update.return_value.eq.return_value.execute.return_value = MagicMock()
        return mock_t

    mock_supabase.table.side_effect = table_mock

    mock_chunker = MagicMock()
    mock_chunker.chunk_document.return_value = (dummy_parents, dummy_children)
    mock_qdrant = MagicMock()

    with patch("app.services.ingestion.celery_tasks.get_service_role_client", return_value=mock_supabase), \
         patch("app.services.ingestion.celery_tasks.pdf_extracter", return_value="Extracted markdown"), \
         patch("app.services.ingestion.celery_tasks.HierarchicalChunker", return_value=mock_chunker), \
         patch("app.services.ingestion.celery_tasks.QdrantManager", return_value=mock_qdrant):

        # Execute task function directly using .run() without hitting Celery broker
        process_pdf_task.run(source_id=source_id, user_id=user_id)

        # 650 chunks with batch size 250 should produce exactly 3 batches: 250, 250, 150
        assert len(inserted_batches) == 3
        assert len(inserted_batches[0]) == 250
        assert len(inserted_batches[1]) == 250
        assert len(inserted_batches[2]) == 150

        # Total chunks inserted must equal 650
        total_inserted = sum(len(b) for b in inserted_batches)
        assert total_inserted == 650

        # Verify correct chunk indices and ordering preserved
        assert inserted_batches[0][0]["chunk_index"] == 0
        assert inserted_batches[0][249]["chunk_index"] == 249
        assert inserted_batches[1][0]["chunk_index"] == 250
        assert inserted_batches[2][149]["chunk_index"] == 649
