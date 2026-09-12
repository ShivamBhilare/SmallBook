"""Study Concurrency & Rate Limiting Module.

Provides distributed locking and cooldown management to prevent concurrent
study generation runs and enforce per-tool generation intervals using Redis
with local in-memory TTL fallbacks.
"""

import logging
import time
from typing import Dict, Tuple

from app.core.redis_client import get_redis_client

logger = logging.getLogger(__name__)


class ExpiringLockDict(dict):
    """Thread-safe in-memory lock store supporting TTL expiration.

    Provides set-like `.discard()` and `.add()` methods to maintain backward
    compatibility with earlier in-memory set-based implementations while
    supporting automatic time-based invalidation.
    """

    def discard(self, key: str) -> None:
        """Removes a key from the lock store if present.

        Args:
            key: User identifier or lock token.
        """
        self.pop(key, None)

    def add(self, key: str, timeout_seconds: int = 180) -> None:
        """Adds a key to the lock store with a relative expiration duration.

        Args:
            key: User identifier or lock token.
            timeout_seconds: Duration in seconds before key expires.
        """
        self[key] = time.time() + timeout_seconds

    def __contains__(self, key: object) -> bool:
        """Checks if a key is present and has not exceeded its expiration timestamp.

        Args:
            key: Lock key to evaluate.

        Returns:
            True if key exists and expiration is in the future; False otherwise.
        """
        if not super().__contains__(key):
            return False
        if time.time() >= self.get(key, 0.0):
            self.pop(key, None)
            return False
        return True


# In-memory fallbacks when Redis is temporarily unavailable in local or test environments
_local_locks = ExpiringLockDict()
_local_cooldowns: Dict[str, float] = {}


def acquire_study_lock(user_id: str, timeout_seconds: int = 180) -> bool:
    """Acquires an exclusive generation lock for a user to prevent parallel runs.

    Attempts atomic SETNX with TTL against Redis. Falls back to an in-memory
    dictionary if Redis is offline.

    Args:
        user_id: UUID of the requesting user.
        timeout_seconds: Lock duration in seconds before automatic expiration.

    Returns:
        True if lock was successfully acquired; False if generation is already active.
    """
    client = get_redis_client()
    lock_key = f"lock:study_gen:{user_id}"
    if client:
        try:
            return bool(client.set(lock_key, "active", nx=True, ex=timeout_seconds))
        except Exception as e:
            logger.warning(f"Redis error setting lock {lock_key}: {e}. Falling back to in-memory lock.")

    # In-memory fallback with TTL
    now = time.time()
    expires_at = _local_locks.get(user_id, 0.0)
    if now < expires_at:
        return False
    _local_locks[user_id] = now + timeout_seconds
    return True


def release_study_lock(user_id: str) -> None:
    """Releases the exclusive study generation lock for a user.

    Clears both the Redis key and any local fallback lock state.

    Args:
        user_id: UUID of the user releasing their generation lock.
    """
    client = get_redis_client()
    lock_key = f"lock:study_gen:{user_id}"
    if client:
        try:
            client.delete(lock_key)
        except Exception as e:
            logger.warning(f"Redis error releasing lock {lock_key}: {e}")

    # In-memory fallback cleanup
    _local_locks.discard(user_id)


def check_and_set_cooldown(user_id: str, tool_type: str, cooldown_seconds: int = 1800) -> Tuple[bool, int]:
    """Checks if a user is within a generation cooldown and sets it if eligible.

    Prevents abuse and quota exhaustion on free LLM endpoints by enforcing a
    per-user, per-tool generation interval (default 30 minutes / 1800 seconds).

    Args:
        user_id: UUID of the requesting user.
        tool_type: Tool identifier ('flashcards' or 'quiz').
        cooldown_seconds: Cooldown duration in seconds to set if eligible.

    Returns:
        Tuple containing:
            - allowed: True if generation is allowed and cooldown was set; False if blocked.
            - remaining_seconds: 0 if allowed, or remaining seconds of active cooldown.
    """
    client = get_redis_client()
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


def get_cooldown_remaining(user_id: str, tool_type: str) -> int:
    """Returns remaining cooldown seconds without mutating the active timer.

    Args:
        user_id: UUID of the user.
        tool_type: Tool identifier ('flashcards' or 'quiz').

    Returns:
        Remaining cooldown duration in seconds, or 0 if eligible.
    """
    client = get_redis_client()
    cd_key = f"cooldown:study:{tool_type}:{user_id}"

    if client:
        try:
            ttl = client.ttl(cd_key)
            if ttl is not None and ttl > 0:
                return ttl
            return 0
        except Exception as e:
            logger.warning(f"Redis error peeking cooldown {cd_key}: {e}. Checking in-memory.")

    # In-memory fallback
    now = time.time()
    mem_key = f"{tool_type}:{user_id}"
    expires_at = _local_cooldowns.get(mem_key, 0.0)
    if now < expires_at:
        return max(0, int(expires_at - now))
    return 0


def clear_cooldown(user_id: str, tool_type: str) -> None:
    """Clears active cooldown timer for a user on generation failure or test reset.

    Args:
        user_id: UUID of the user.
        tool_type: Tool identifier ('flashcards' or 'quiz').
    """
    client = get_redis_client()
    cd_key = f"cooldown:study:{tool_type}:{user_id}"
    if client:
        try:
            client.delete(cd_key)
        except Exception:
            pass

    mem_key = f"{tool_type}:{user_id}"
    _local_cooldowns.pop(mem_key, None)
