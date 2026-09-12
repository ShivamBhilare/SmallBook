"""Authentication and Landing Page Test Suite for SmallBook.

Validates:
- Resend verification email service logic and Supabase payload generation.
- Async API resend verification endpoint behavior (success and rate-limit error branches).
- Verification email landing page rendering with email query parameter injection.
- Root landing page (/) and alias (/landing) marketing view delivery.
"""

import asyncio
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.models.auth_models import ForgotPasswordSchema
from app.routers.auth import api_resend_verification
from app.services.authentication.auth_service import resend_verification_email
from main import app

client = TestClient(app)


def test_resend_verification_email_service():
    """Verifies that resend_verification_email calls client.auth.resend with correct payload.

    Pattern:
        - Arrange: Mock Supabase client instance with auth.resend mock.
        - Act: Call resend_verification_email with target email address.
        - Assert: Verify client.auth.resend was called once with type='signup' and the email.
    """
    mock_supabase = MagicMock()
    mock_supabase.auth.resend.return_value = MagicMock()

    resend_verification_email(mock_supabase, "student@example.com")
    mock_supabase.auth.resend.assert_called_once_with({
        "type": "signup",
        "email": "student@example.com"
    })


def test_api_resend_verification_endpoint():
    """Tests the POST /auth/api/resend-verification endpoint direct invocation.

    Pattern:
        - Arrange: Mock Supabase client and instantiate ForgotPasswordSchema payload.
        - Act: Directly execute async api_resend_verification coroutine.
        - Assert: Verify response dictionary contains status='success' and expected confirmation message.
    """
    mock_supabase = MagicMock()
    mock_supabase.auth.resend.return_value = MagicMock()

    # Direct async call to endpoint
    payload = ForgotPasswordSchema(email="user@test.com")
    res = asyncio.run(api_resend_verification(data=payload, client=mock_supabase))

    assert res["status"] == "success"
    assert "Verification link has been resent" in res["message"]
    mock_supabase.auth.resend.assert_called_once_with({
        "type": "signup",
        "email": "user@test.com"
    })


def test_api_resend_verification_error():
    """Verifies error handling when Supabase auth resend raises an exception.

    Pattern:
        - Arrange: Mock Supabase client raising Exception('Rate limit exceeded').
        - Act & Assert: Call api_resend_verification within pytest.raises(HTTPException),
          confirming status_code 400 and expected error detail in exception.
    """
    mock_supabase = MagicMock()
    mock_supabase.auth.resend.side_effect = Exception("Rate limit exceeded")

    payload = ForgotPasswordSchema(email="user@test.com")
    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(api_resend_verification(data=payload, client=mock_supabase))

    assert exc_info.value.status_code == 400
    assert "Rate limit exceeded" in exc_info.value.detail


def test_read_verify_email_page():
    """Verifies GET /auth/verify-email renders correctly with query parameter.

    Pattern:
        - Arrange: Prepare client GET request with query param `email=learner@university.edu`.
        - Act: Issue request via TestClient.
        - Assert: Verify HTTP 200 and presence of expected template strings and Alpine state handler.
    """
    resp = client.get("/auth/verify-email?email=learner@university.edu")
    assert resp.status_code == 200
    assert "Check your email" in resp.text
    assert "Click to resend link" in resp.text
    assert "verifyEmailState" in resp.text


def test_read_landing_page():
    """Verifies GET / renders the SmallBook landing page with CTAs and core features.

    Pattern:
        - Arrange: TestClient ready.
        - Act: Issue GET request to root URL ('/').
        - Assert: Verify HTTP 200 and key landing landmarks (branding, auth links, feature badges).
    """
    resp = client.get("/")
    assert resp.status_code == 200
    assert "SmallBook" in resp.text
    assert "/auth/sign-up" in resp.text
    assert "/auth/sign-in" in resp.text
    assert "Strictly Grounded" in resp.text
    assert "Strict Mode" in resp.text
    assert "Flashcards" in resp.text


def test_read_landing_alias():
    """Verifies GET /landing renders the landing page identically.

    Pattern:
        - Arrange: TestClient ready.
        - Act: Issue GET request to alias URL ('/landing').
        - Assert: Verify HTTP 200, branding, and sign-up links.
    """
    resp = client.get("/landing")
    assert resp.status_code == 200
    assert "SmallBook" in resp.text
    assert "/auth/sign-up" in resp.text
