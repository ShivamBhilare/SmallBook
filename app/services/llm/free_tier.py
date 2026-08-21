import os
import time
from datetime import datetime, timezone
from typing import Tuple, Optional, Dict, Any
import redis
from dotenv import load_dotenv

load_dotenv()

# Redis Connection setup for distributed rate limiting
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")

_redis_client: Optional[redis.Redis] = None
_redis_last_check: float = 0.0

def get_redis_client() -> Optional[redis.Redis]:
    global _redis_client, _redis_last_check
    now = time.time()
    # Cache connection status for 10 seconds if offline to avoid connection lag
    if _redis_client is None and (now - _redis_last_check < 10.0):
        return None

    _redis_last_check = now
    if _redis_client is None:
        try:
            client = redis.from_url(
                REDIS_URL,
                decode_responses=True,
                socket_timeout=0.3,
                socket_connect_timeout=0.3
            )
            client.ping()
            _redis_client = client
        except Exception:
            _redis_client = None
    return _redis_client


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
        except Exception:
            pass

    # Memory check
    mem_key = f"{user_id}:{today_str}"
    if mem_key in _memory_daily_counts:
        used = _memory_daily_counts[mem_key]
        remaining = max(0, limit - used)
        return (used < limit, used, remaining)

    # Supabase check if client provided
    if client:
        try:
            db_res = client.table("user_free_tier_usage").select("request_count").eq("user_id", user_id).eq("usage_date", today_str).execute()
            if db_res.data and len(db_res.data) > 0:
                used = db_res.data[0].get("request_count", 0)
                _memory_daily_counts[mem_key] = used
                remaining = max(0, limit - used)
                return (used < limit, used, remaining)
        except Exception:
            pass

    return (True, 0, limit)


def increment_daily_quota(user_id: str, limit: int = 25, client: Optional[Any] = None) -> int:
    """
    Increments the daily quota counter for a user across Redis, Memory, and Supabase.
    Returns the new used count.
    """
    today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    redis_key = f"smallbook:freetier:daily:{user_id}:{today_str}"
    
    new_count = 1
    r = get_redis_client()
    if r:
        try:
            pipe = r.pipeline()
            pipe.incr(redis_key)
            pipe.expire(redis_key, 86400 * 2)  # 48 hour TTL
            res = pipe.execute()
            new_count = int(res[0])
        except Exception:
            pass

    mem_key = f"{user_id}:{today_str}"
    _memory_daily_counts[mem_key] = _memory_daily_counts.get(mem_key, 0) + 1
    if new_count == 1:
        new_count = _memory_daily_counts[mem_key]

    # Sync to Supabase user_free_tier_usage for persistence & analytics
    if client:
        try:
            client.table("user_free_tier_usage").upsert({
                "user_id": user_id,
                "usage_date": today_str,
                "request_count": new_count
            }, on_conflict="user_id,usage_date").execute()
        except Exception:
            pass

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


def get_free_tier_status(user_id: str, limit: int = 25) -> Dict[str, Any]:
    """Returns a full status dictionary for frontend badge & modal display."""
    allowed, used, remaining = check_daily_quota(user_id, limit=limit)
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
