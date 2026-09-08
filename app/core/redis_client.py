import os
import time
import logging
from typing import Optional
import redis
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")

_redis_client: Optional[redis.Redis] = None
_redis_pool: Optional[redis.ConnectionPool] = None
_redis_last_failure: float = 0.0
_OFFLINE_RETRY_INTERVAL: float = 10.0  # Seconds to wait before re-attempting connection when Redis is offline


def get_redis_client() -> Optional[redis.Redis]:
    """
    Returns a shared, pooled Redis client instance.
    If Redis is offline, caches the offline status for 10 seconds to eliminate
    socket connection latency on subsequent requests during local development.
    """
    global _redis_client, _redis_pool, _redis_last_failure
    now = time.time()

    # Fast-path: if recently failed, avoid blocking socket timeouts
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
    Primary use cases: testing isolation, reconnecting after config change.
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
