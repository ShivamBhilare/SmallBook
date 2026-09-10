from app.services.llm.free_tier import (
    check_daily_quota,
    increment_daily_quota,
    check_burst_limit,
    get_free_tier_status,
)

def test_daily_quota_limits():
    test_user_id = "user_test_quota_123"
    
    # Check initial quota
    allowed, used, remaining = check_daily_quota(test_user_id, limit=25)
    assert allowed is True
    assert remaining >= 0
    
    # Increment quota
    new_count = increment_daily_quota(test_user_id, limit=25)
    assert new_count >= 1
    
    # Check updated status
    allowed_after, used_after, remaining_after = check_daily_quota(test_user_id, limit=25)
    assert used_after == new_count
    assert remaining_after == 25 - new_count

def test_burst_limiter():
    test_user_id = "user_test_burst_456"
    
    # First 3 rapid calls should succeed
    assert check_burst_limit(test_user_id, max_per_minute=3) is True
    assert check_burst_limit(test_user_id, max_per_minute=3) is True
    assert check_burst_limit(test_user_id, max_per_minute=3) is True
    
    # 4th call should hit burst limit
    assert check_burst_limit(test_user_id, max_per_minute=3) is False

def test_free_tier_status_payload():
    status = get_free_tier_status("user_status_test", limit=25)
    assert "is_available" in status
    assert "daily_limit" in status
    assert status["daily_limit"] == 25
    assert "primary_model" in status
    assert "secondary_model" in status


def test_increment_daily_quota_redis_sync():
    from unittest.mock import patch, MagicMock
    from app.services.llm.free_tier import _memory_daily_counts
    
    mock_redis = MagicMock()
    mock_pipe = MagicMock()
    mock_pipe.execute.return_value = [5]  # Redis reports 5
    mock_redis.pipeline.return_value = mock_pipe

    test_user_id = "user_test_redis_sync_789"
    with patch("app.services.llm.free_tier.get_redis_client", return_value=mock_redis):
        count = increment_daily_quota(test_user_id, limit=25)
        assert count == 5
        # Verify in-memory count was synchronized to 5
        from datetime import datetime, timezone
        today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        assert _memory_daily_counts[f"{test_user_id}:{today_str}"] == 5


def test_increment_daily_quota_offline_fallback():
    from unittest.mock import patch

    test_user_id = "user_test_offline_999"
    with patch("app.services.llm.free_tier.get_redis_client", return_value=None):
        count_1 = increment_daily_quota(test_user_id, limit=25)
        count_2 = increment_daily_quota(test_user_id, limit=25)
        assert count_2 == count_1 + 1


def test_quota_persists_across_restart_via_supabase():
    from unittest.mock import patch, MagicMock
    from app.services.llm.free_tier import _memory_daily_counts, check_daily_quota, increment_daily_quota, get_free_tier_status
    from datetime import datetime, timezone

    test_user_id = "11111111-2222-3333-4444-555555555555"
    today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    mem_key = f"{test_user_id}:{today_str}"

    # Mock Supabase client returning 12 queries already used today
    mock_supabase = MagicMock()
    mock_table = MagicMock()
    mock_select = MagicMock()
    mock_eq1 = MagicMock()
    mock_eq2 = MagicMock()
    mock_eq2.execute.return_value = MagicMock(data=[{"request_count": 12}])
    mock_eq1.eq.return_value = mock_eq2
    mock_select.eq.return_value = mock_eq1
    mock_table.select.return_value = mock_select
    mock_table.upsert.return_value = MagicMock(execute=MagicMock())
    mock_supabase.table.return_value = mock_table

    # Simulate app restart: Redis is offline, memory cache is completely wiped
    _memory_daily_counts.pop(mem_key, None)

    with patch("app.services.llm.free_tier.get_redis_client", return_value=None):
        # 1. Checking quota status should hydrate 12 used, 13 remaining
        allowed, used, remaining = check_daily_quota(test_user_id, limit=25, client=mock_supabase)
        assert allowed is True
        assert used == 12
        assert remaining == 13

        # 2. get_free_tier_status should reflect this
        status = get_free_tier_status(test_user_id, limit=25, client=mock_supabase)
        assert status["used_today"] == 12
        assert status["remaining_today"] == 13

        # 3. Simulate another memory wipe (another restart), then user sends another message
        _memory_daily_counts.pop(mem_key, None)
        new_count = increment_daily_quota(test_user_id, limit=25, client=mock_supabase)
        # It must increment from 12 to 13, NOT reset to 1
        assert new_count == 13

