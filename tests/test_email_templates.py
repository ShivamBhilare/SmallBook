"""Tests for SmallBook Transactional Email Templates and Preview Studio.

Verifies that:
1. All Jinja2 email templates render cleanly with expected context variables.
2. All standalone Supabase GoTrue templates exist and contain required GoTrue tags.
3. The developer email preview studio and render endpoints return HTTP 200 OK.
"""

import os
import pytest
from starlette.testclient import TestClient
from fastapi.templating import Jinja2Templates
from main import app

client = TestClient(app)
templates = Jinja2Templates(directory="app/templates")


def test_jinja2_email_templates_render_successfully():
    """Verifies that all 4 Jinja2 email templates render with correct context variables."""
    # 1. Verify Email
    verify_html = templates.get_template("emails/verify_email.html").render({
        "user_name": "Test Student",
        "email": "student@university.edu",
        "confirmation_url": "https://smallbook.ai/auth/confirm?token=xyz123",
        "site_url": "https://smallbook.ai"
    })
    assert "Welcome to SmallBook!" in verify_html
    assert "Test Student" in verify_html
    assert "student@university.edu" in verify_html
    assert "https://smallbook.ai/auth/confirm?token=xyz123" in verify_html
    assert "Confirm Email Address" in verify_html

    # 2. Reset Password
    reset_html = templates.get_template("emails/reset_password.html").render({
        "email": "student@university.edu",
        "confirmation_url": "https://smallbook.ai/auth/reset?token=abc456",
        "site_url": "https://smallbook.ai"
    })
    assert "Reset Your Password" in reset_html
    assert "student@university.edu" in reset_html
    assert "https://smallbook.ai/auth/reset?token=abc456" in reset_html
    assert "1 hour" in reset_html

    # 3. Magic Link
    magic_html = templates.get_template("emails/magic_link.html").render({
        "email": "student@university.edu",
        "confirmation_url": "https://smallbook.ai/auth/magic?token=mag789",
        "token": "492018",
        "site_url": "https://smallbook.ai"
    })
    assert "Instant Sign In" in magic_html
    assert "492018" in magic_html
    assert "10 minutes" in magic_html

    # 4. Change Email
    change_html = templates.get_template("emails/change_email.html").render({
        "email": "new.email@university.edu",
        "confirmation_url": "https://smallbook.ai/auth/change?token=chg321",
        "site_url": "https://smallbook.ai"
    })
    assert "Confirm Email Change" in change_html
    assert "new.email@university.edu" in change_html
    assert "https://smallbook.ai/auth/change?token=chg321" in change_html


def test_supabase_gotrue_templates_dynamically_generated():
    """Verifies that all Supabase GoTrue HTML templates are dynamically generated with required tags."""
    email_types_and_tags = {
        "verify": ["{{ .ConfirmationURL }}", "{{ .Email }}", "Welcome to SmallBook!"],
        "reset": ["{{ .ConfirmationURL }}", "{{ .Email }}", "Reset Your Password"],
        "magic_link": ["{{ .ConfirmationURL }}", "Instant Sign In"],
        "change_email": ["{{ .ConfirmationURL }}", "Confirm Email Change"],
    }

    for email_type, expected_strings in email_types_and_tags.items():
        res = client.get(f"/dev/emails/raw/{email_type}")
        assert res.status_code == 200
        data = res.json()
        assert "html" in data
        html_content = data["html"]
        assert "SmallBooklogo.png" in html_content
        for s in expected_strings:
            assert s in html_content, f"Generated template for {email_type} must contain '{s}'"


def test_dev_emails_endpoints():
    """Verifies that the developer email preview studio and render endpoints return HTTP 200 in light theme."""
    # Main studio dashboard
    res = client.get("/dev/emails")
    assert res.status_code == 200
    assert "Email Studio" in res.text
    assert "Confirm Registration" in res.text

    # Individual render endpoints (warm paper light theme)
    for email_type in ["verify", "reset", "magic_link", "change_email"]:
        render_res = client.get(f"/dev/emails/render/{email_type}")
        assert render_res.status_code == 200
        assert "SmallBook" in render_res.text
        assert "#faf9f5" in render_res.text  # Warm paper background
        assert "#9c4323" in render_res.text  # Terracotta accent

        # Raw HTML json endpoint
        raw_res = client.get(f"/dev/emails/raw/{email_type}")
        assert raw_res.status_code == 200
        data = raw_res.json()
        assert "html" in data
        assert len(data["html"]) > 100

    # 404 for unknown type
    bad_res = client.get("/dev/emails/render/unknown_type")
    assert bad_res.status_code == 404
