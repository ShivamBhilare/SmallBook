import pytest
from unittest.mock import MagicMock
from fastapi.testclient import TestClient
from fastapi import HTTPException

from main import app
from app.models.auth_models import ForgotPasswordSchema
from app.services.authentication.auth_service import resend_verification_email
from app.routers.auth import api_resend_verification

client = TestClient(app)


def test_resend_verification_email_service():
    """Verifies that resend_verification_email calls client.auth.resend with correct payload."""
    mock_supabase = MagicMock()
    mock_supabase.auth.resend.return_value = MagicMock()

    resend_verification_email(mock_supabase, "student@example.com")
    mock_supabase.auth.resend.assert_called_once_with({
        "type": "signup",
        "email": "student@example.com"
    })


def test_api_resend_verification_endpoint():
    """Tests POST /auth/api/resend-verification endpoint."""
    mock_supabase = MagicMock()
    mock_supabase.auth.resend.return_value = MagicMock()

    # Direct async call to endpoint
    payload = ForgotPasswordSchema(email="user@test.com")
    import asyncio
    res = asyncio.run(api_resend_verification(data=payload, client=mock_supabase))

    assert res["status"] == "success"
    assert "Verification link has been resent" in res["message"]
    mock_supabase.auth.resend.assert_called_once_with({
        "type": "signup",
        "email": "user@test.com"
    })


def test_api_resend_verification_error():
    """Verifies error handling when Supabase auth resend fails."""
    mock_supabase = MagicMock()
    mock_supabase.auth.resend.side_effect = Exception("Rate limit exceeded")

    payload = ForgotPasswordSchema(email="user@test.com")
    import asyncio
    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(api_resend_verification(data=payload, client=mock_supabase))

    assert exc_info.value.status_code == 400
    assert "Rate limit exceeded" in exc_info.value.detail


def test_read_verify_email_page():
    """Verifies GET /auth/verify-email renders correctly with query parameter."""
    resp = client.get("/auth/verify-email?email=learner@university.edu")
    assert resp.status_code == 200
    assert "Check your email" in resp.text
    assert "Click to resend link" in resp.text
    assert "verifyEmailState" in resp.text
