"""
Redis Connection Pooling & Client Lifecycle Management

Provides a shared, thread-safe Redis client backed by a ConnectionPool.
Implements a fast-failing circuit breaker pattern for offline instances during local
development, preventing blocking socket timeouts from degrading API response times.
Used across SmallBook for Celery broker coordination, distributed concurrency locks,
and free-tier usage tracking.
"""

import os
import time
import logging
from typing import Optional
import redis
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

# Primary Redis connection URI parsed from environment or defaulting to local Redis port
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")

# Internal singleton handles and offline throttle state
_redis_client: Optional[redis.Redis] = None
_redis_pool: Optional[redis.ConnectionPool] = None
_redis_last_failure: float = 0.0
_OFFLINE_RETRY_INTERVAL: float = 10.0  # Seconds to wait before re-attempting connection when Redis is offline


def get_redis_client() -> Optional[redis.Redis]:
    """
    Returns a shared, pooled Redis client instance with offline circuit breaker protection.

    Reuses an existing connection pool to minimize handshake overhead. If Redis is detected
    as offline or unreachable, caches the failure timestamp and immediately returns `None`
    for subsequent calls within the 10-second window, avoiding costly blocking socket timeouts.

    Returns:
        Optional[redis.Redis]: Active, ping-tested Redis client instance, or None if Redis
            is currently unreachable.
    """
    global _redis_client, _redis_pool, _redis_last_failure
    now = time.time()

    # Fast-path circuit breaker: if recently failed, avoid blocking socket timeouts
    if _redis_client is None and (now - _redis_last_failure < _OFFLINE_RETRY_INTERVAL):
        return None

    if _redis_client is None:
        try:
            if _redis_pool is None:
                _redis_pool = redis.ConnectionPool.from_url(
                    REDIS_URL,
                    decode_responses=True,
                    max_connections=20,
                    socket_timeout=1.0,
                    socket_connect_timeout=1.0
                )
            client = redis.Redis(connection_pool=_redis_pool)
            client.ping()
            _redis_client = client
        except Exception as e:
            _redis_last_failure = now
            _redis_client = None
            logger.debug(f"Redis is unavailable at {REDIS_URL}: {e}")
            return None

    return _redis_client


def reset_redis_client() -> None:
    """
    Closes existing Redis connections and resets the client and pool singletons.

    Disconnects all active sockets in the connection pool and resets the offline failure
    timer. Primarily utilized in automated test suites (pytest fixtures) to ensure
    clean connection isolation between test cases.
    """
    global _redis_client, _redis_pool, _redis_last_failure
    if _redis_client is not None:
        try:
            _redis_client.close()
        except Exception:
            pass
    if _redis_pool is not None:
        try:
            _redis_pool.disconnect()
        except Exception:
            pass
    _redis_client = None
    _redis_pool = None
    _redis_last_failure = 0.0

