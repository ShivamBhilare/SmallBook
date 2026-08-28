import os
import time
import logging
from typing import Tuple, Dict
import redis

logger = logging.getLogger(__name__)

REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379/0")

# In-memory fallbacks if Redis is temporarily offline in local dev
_local_locks = set()
_local_cooldowns: Dict[str, float] = {}

def _get_redis_client():
    try:
        return redis.Redis.from_url(REDIS_URL, socket_timeout=2.0)
    except Exception as e:
        logger.warning(f"Failed to connect to Redis for study concurrency: {e}")
        return None

def acquire_study_lock(user_id: str, timeout_seconds: int = 180) -> bool:
    """
    Acquires an exclusive generation lock for the user to prevent parallel runs.
    Returns True if acquired, False if another generation is already in progress.
    """
    client = _get_redis_client()
    lock_key = f"lock:study_gen:{user_id}"
    if client:
        try:
            return bool(client.set(lock_key, "active", nx=True, ex=timeout_seconds))
        except Exception as e:
            logger.warning(f"Redis error setting lock {lock_key}: {e}. Falling back to in-memory lock.")
    
    # In-memory fallback
    if user_id in _local_locks:
        return False
    _local_locks.add(user_id)
    return True

def release_study_lock(user_id: str) -> None:
    """
    Releases the study generation lock for the user.
    """
    client = _get_redis_client()
    lock_key = f"lock:study_gen:{user_id}"
    if client:
        try:
            client.delete(lock_key)
        except Exception as e:
            logger.warning(f"Redis error releasing lock {lock_key}: {e}")
    
    # In-memory fallback cleanup
    _local_locks.discard(user_id)


def check_and_set_cooldown(user_id: str, tool_type: str, cooldown_seconds: int = 1800) -> Tuple[bool, int]:
    """
    Checks if a user is within the 30-minute cooldown (1800s) for the specified tool type (flashcards/quiz).
    Returns:
        (True, 0) if user can generate (cooldown set).
        (False, remaining_seconds) if blocked by active cooldown.
    """
    client = _get_redis_client()
    cd_key = f"cooldown:study:{tool_type}:{user_id}"
    
    if client:
        try:
            # Check if key exists
            ttl = client.ttl(cd_key)
            if ttl is not None and ttl > 0:
                return False, ttl
            
            # Set new cooldown
            client.set(cd_key, "active", ex=cooldown_seconds)
            return True, 0
        except Exception as e:
            logger.warning(f"Redis error checking cooldown {cd_key}: {e}. Falling back to in-memory cooldown.")

    # In-memory fallback
    now = time.time()
    mem_key = f"{tool_type}:{user_id}"
    expires_at = _local_cooldowns.get(mem_key, 0.0)
    
    if now < expires_at:
        remaining = int(expires_at - now)
        return False, remaining
    
    _local_cooldowns[mem_key] = now + cooldown_seconds
    return True, 0


def clear_cooldown(user_id: str, tool_type: str) -> None:
    """Clears cooldown (e.g. on generation failure or test cleanup)."""
    client = _get_redis_client()
    cd_key = f"cooldown:study:{tool_type}:{user_id}"
    if client:
        try:
            client.delete(cd_key)
        except Exception:
            pass
    
    mem_key = f"{tool_type}:{user_id}"
    _local_cooldowns.pop(mem_key, None)
