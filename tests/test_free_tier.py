import pytest
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
