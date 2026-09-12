"""
Developer Free-Tier Rate Limiting & Quota Management Subsystem

Enforces daily query limits and anti-spam burst controls on developer-subsidized
free LLM inference (Groq GPT-OSS and Gemini Flash). Implements a resilient 3-tier
state hierarchy:
    1. Tier 1 (Fast-path): Redis sliding window counters and daily increment keys.
    2. Tier 2 (Local Dev Fallback): In-memory dictionary tracking when Redis is offline.
    3. Tier 3 (Durable Source of Truth): Supabase PostgreSQL `user_free_tier_usage` table.
"""

import os
import time
import logging
import uuid
from datetime import datetime, timezone
from typing import Tuple, Optional, Dict, Any
from dotenv import load_dotenv

from app.core.redis_client import get_redis_client

load_dotenv()

logger = logging.getLogger(__name__)

# In-memory fallback tracking in case Redis is offline during local development
_memory_daily_counts: Dict[str, int] = {}
_memory_burst_timestamps: Dict[str, list] = {}


# =========================================================================
# 1. DEVELOPER KEY RESOLUTION
# =========================================================================

def get_developer_groq_key() -> Optional[str]:
    """
    Retrieves the developer-provided Groq API key from environment variables.

    Returns:
        Optional[str]: Stripped API key string, or None if not configured.
    """
    key = os.getenv("DEVELOPER_GROQ_KEY") or os.getenv("GROQ_API_KEY")
    return key.strip() if key else None


def get_developer_gemini_key() -> Optional[str]:
    """
    Retrieves the developer-provided Google Gemini API key from environment variables.

    Returns:
        Optional[str]: Stripped API key string, or None if not configured.
    """
    key = os.getenv("DEVELOPER_GEMINI_KEY") or os.getenv("GEMINI_API_KEY")
    return key.strip() if key else None


# =========================================================================
# 2. INTERNAL VALIDATION & CLIENT HELPERS
# =========================================================================

def _is_valid_uuid(val: str) -> bool:
    """
    Checks if a given string conforms to standard UUID formatting.

    Args:
        val: String to validate.

    Returns:
        bool: True if valid UUID, False otherwise.
    """
    try:
        uuid.UUID(str(val))
        return True
    except (ValueError, AttributeError):
        return False


def _get_db_client(client: Optional[Any] = None) -> Optional[Any]:
    """
    Returns an administrative Supabase client for reliable quota operations.

    If a test mock is supplied, uses it directly. Otherwise resolves the service role
    client so that user JWT or Row-Level Security (RLS) constraints do not impede
    system-level quota accounting.

    Args:
        client: Optional client or test mock override.

    Returns:
        Optional[Any]: Client instance for database quota queries.
    """
    if client is not None:
        from unittest.mock import Mock, MagicMock
        if isinstance(client, (Mock, MagicMock)):
            return client

    try:
        from app.services.authentication.auth_service import get_service_role_client
        return get_service_role_client()
    except Exception as e:
        logger.error(f"Failed to get service role client for quota persistence: {e}")
        return client


# =========================================================================
# 3. DAILY QUOTA & BURST LIMIT CONTROLS
# =========================================================================

def check_daily_quota(
    user_id: str,
    limit: int = 25,
    client: Optional[Any] = None
) -> Tuple[bool, int, int]:
    """
    Checks if a user has remaining free-tier queries for today (UTC).

    Evaluates Redis first; falls back to in-memory tracking or PostgreSQL if Redis is offline.

    Args:
        user_id: Unique UUID string of the requesting user.
        limit: Daily query cap (defaults to 25 queries).
        client: Optional database client override.

    Returns:
        Tuple[bool, int, int]: (is_allowed, used_today, remaining_today).
    """
    today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    redis_key = f"smallbook:freetier:daily:{user_id}:{today_str}"
    
    r = get_redis_client()
    if r:
        try:
            current_val = r.get(redis_key)
            if current_val is not None:
                used = int(current_val)
                remaining = max(0, limit - used)
                return (used < limit, used, remaining)
        except Exception as e:
            logger.debug(f"Redis get failed: {e}")

    # Memory check
    mem_key = f"{user_id}:{today_str}"
    if mem_key in _memory_daily_counts:
        used = _memory_daily_counts[mem_key]
        remaining = max(0, limit - used)
        return (used < limit, used, remaining)

    # Supabase persistent check (admin client bypasses RLS)
    sb_client = _get_db_client(client)
    if sb_client and _is_valid_uuid(user_id):
        try:
            db_res = sb_client.table("user_free_tier_usage").select("request_count").eq("user_id", user_id).eq("usage_date", today_str).execute()
            if db_res.data and len(db_res.data) > 0:
                used = db_res.data[0].get("request_count", 0)
                _memory_daily_counts[mem_key] = used
                remaining = max(0, limit - used)
                return (used < limit, used, remaining)
        except Exception as e:
            logger.error(f"Failed to query daily quota from Supabase for user {user_id}: {e}")

    return (True, 0, limit)


def increment_daily_quota(
    user_id: str,
    limit: int = 25,
    client: Optional[Any] = None
) -> int:
    """
    Increments the daily quota counter for a user across Redis, Memory, and Supabase.

    Maintains cache synchronization across the multi-tier storage layers and persists
    the updated count to the `user_free_tier_usage` PostgreSQL table for analytics.

    Args:
        user_id: Unique UUID string of the requesting user.
        limit: Daily query cap.
        client: Optional database client override.

    Returns:
        int: The newly updated query count for today.
    """
    today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    redis_key = f"smallbook:freetier:daily:{user_id}:{today_str}"
    mem_key = f"{user_id}:{today_str}"
    
    redis_success = False
    new_count = 1
    r = get_redis_client()
    if r:
        try:
            pipe = r.pipeline()
            pipe.incr(redis_key)
            pipe.expire(redis_key, 86400 * 2)  # 48 hour TTL
            res = pipe.execute()
            new_count = int(res[0])
            redis_success = True
        except Exception as e:
            logger.debug(f"Redis pipeline failed: {e}")
            redis_success = False

    sb_client = _get_db_client(client)

    if redis_success:
        # Keep in-memory cache synchronized with Redis truth
        _memory_daily_counts[mem_key] = new_count
    else:
        # If memory cache is empty (e.g. after app restart), hydrate previous count from Supabase first
        if mem_key not in _memory_daily_counts:
            if sb_client and _is_valid_uuid(user_id):
                try:
                    db_res = sb_client.table("user_free_tier_usage").select("request_count").eq("user_id", user_id).eq("usage_date", today_str).execute()
                    if db_res.data and len(db_res.data) > 0:
                        _memory_daily_counts[mem_key] = db_res.data[0].get("request_count", 0)
                except Exception as e:
                    logger.error(f"Failed to hydrate quota from Supabase for user {user_id}: {e}")

        # Increment and fallback to in-memory tracking when Redis is offline
        _memory_daily_counts[mem_key] = _memory_daily_counts.get(mem_key, 0) + 1
        new_count = _memory_daily_counts[mem_key]

    # Sync to Supabase user_free_tier_usage for persistence & analytics
    if sb_client and _is_valid_uuid(user_id):
        try:
            sb_client.table("user_free_tier_usage").upsert({
                "user_id": user_id,
                "usage_date": today_str,
                "request_count": new_count
            }, on_conflict="user_id,usage_date").execute()
        except Exception as e:
            logger.error(f"Failed to persist daily quota to Supabase for user {user_id}: {e}")

    return new_count


def check_burst_limit(user_id: str, max_per_minute: int = 4) -> bool:
    """
    Anti-spam burst limiter using a 60-second sliding window.

    Prevents bot spam or accidental double-submits from consuming daily quotas instantly.
    Uses Redis sorted sets (`ZADD` / `ZREMRANGEBYSCORE`) with in-memory fallback.

    Args:
        user_id: Unique UUID string of the requesting user.
        max_per_minute: Maximum permitted requests in a 60-second window.

    Returns:
        bool: True if allowed under burst limit, False if rate-limited.
    """
    now = time.time()
    r = get_redis_client()
    if r:
        try:
            redis_key = f"smallbook:freetier:burst:{user_id}"
            pipe = r.pipeline()
            pipe.zremrangebyscore(redis_key, 0, now - 60)
            pipe.zadd(redis_key, {str(now): now})
            pipe.zcard(redis_key)
            pipe.expire(redis_key, 120)
            _, _, count, _ = pipe.execute()
            return count <= max_per_minute
        except Exception:
            pass

    # Memory fallback
    timestamps = _memory_burst_timestamps.get(user_id, [])
    timestamps = [t for t in timestamps if now - t < 60]
    timestamps.append(now)
    _memory_burst_timestamps[user_id] = timestamps
    return len(timestamps) <= max_per_minute


def get_free_tier_status(
    user_id: str,
    limit: int = 25,
    client: Optional[Any] = None
) -> Dict[str, Any]:
    """
    Returns a full status dictionary for frontend badge & modal display.

    Args:
        user_id: Unique UUID string of the requesting user.
        limit: Daily query cap.
        client: Optional database client override.

    Returns:
        Dict[str, Any]: Detailed status dictionary for UI consumption.
    """
    allowed, used, remaining = check_daily_quota(user_id, limit=limit, client=client)
    has_groq = bool(get_developer_groq_key())
    has_gemini = bool(get_developer_gemini_key())
    
    return {
        "is_available": has_groq or has_gemini,
        "is_allowed": allowed,
        "used_today": used,
        "daily_limit": limit,
        "remaining_today": remaining,
        "primary_model": "groq/openai/gpt-oss-120b",
        "secondary_model": "gemini/gemini-2.5-flash",
    }

