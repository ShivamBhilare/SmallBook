import os
import time
import logging
import uuid
from datetime import datetime, timezone
from typing import Tuple, Optional, Dict, Any
from dotenv import load_dotenv

from app.core.redis_client import get_redis_client

load_dotenv()


# In-memory fallback tracking in case Redis is offline during local development
_memory_daily_counts: Dict[str, int] = {}
_memory_burst_timestamps: Dict[str, list] = {}


def get_developer_groq_key() -> Optional[str]:
    """Retrieves developer free-tier Groq API key from environment."""
    key = os.getenv("DEVELOPER_GROQ_KEY") or os.getenv("GROQ_API_KEY")
    return key.strip() if key else None


def get_developer_gemini_key() -> Optional[str]:
    """Retrieves developer free-tier Gemini API key from environment."""
    key = os.getenv("DEVELOPER_GEMINI_KEY") or os.getenv("GEMINI_API_KEY")
    return key.strip() if key else None


logger = logging.getLogger(__name__)


def _is_valid_uuid(val: str) -> bool:
    """Checks if a given string is a valid UUID."""
    try:
        uuid.UUID(str(val))
        return True
    except (ValueError, AttributeError):
        return False


def _get_db_client(client: Optional[Any] = None) -> Optional[Any]:
    """
    Returns an admin Supabase client for reliable quota operations.
    If a test mock is provided, uses it. Otherwise always uses the service role client
    so that user JWT/RLS restrictions never break system rate-limiting.
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


def check_daily_quota(user_id: str, limit: int = 25, client: Optional[Any] = None) -> Tuple[bool, int, int]:
    """
    Checks if a user has remaining free tier queries for today.
    Returns: (is_allowed: bool, used_today: int, remaining_today: int)
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


def increment_daily_quota(user_id: str, limit: int = 25, client: Optional[Any] = None) -> int:
    """
    Increments the daily quota counter for a user across Redis, Memory, and Supabase.
    Returns the new used count.
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
    Anti-spam burst limiter: Prevents rapid-fire requests within a 60-second window.
    Returns True if allowed, False if rate-limited.
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


def get_free_tier_status(user_id: str, limit: int = 25, client: Optional[Any] = None) -> Dict[str, Any]:
    """Returns a full status dictionary for frontend badge & modal display."""
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
