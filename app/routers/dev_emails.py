"""Development Email Previews Router.

Provides an interactive developer studio to preview, inspect, and copy
SmallBook's transactional email templates (Confirm Signup, Password Reset,
Magic Link, Email Change) with responsive viewport and theme toggles.
"""

import os
from typing import Optional
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from app.services.authentication.auth_service import SUPABASE_PUBLIC_LOGO_URL

router = APIRouter(prefix="/dev/emails", tags=["Developer Email Previews"])
templates = Jinja2Templates(directory="app/templates")

# Mock data mapping for template previews
MOCK_EMAIL_DATA = {
    "verify": {
        "title": "Confirm Registration / Verify Email",
        "template": "emails/verify_email.html",
        "context": {
            "user_name": "Shivam Bhilare",
            "email": "shivam.research@example.com",
            "confirmation_url": "http://127.0.0.1:8000/auth/confirm?token=sb_mock_token_verify_894372",
            "site_url": "http://127.0.0.1:8000"
        }
    },
    "reset": {
        "title": "Password Reset / Account Recovery",
        "template": "emails/reset_password.html",
        "context": {
            "email": "shivam.research@example.com",
            "confirmation_url": "http://127.0.0.1:8000/update-password?token=sb_mock_token_reset_302918",
            "site_url": "http://127.0.0.1:8000"
        }
    },
    "magic_link": {
        "title": "Instant Sign In / Magic Link",
        "template": "emails/magic_link.html",
        "context": {
            "email": "shivam.research@example.com",
            "confirmation_url": "http://127.0.0.1:8000/auth/callback?token=sb_mock_token_magic_109283",
            "token": "749201",
            "site_url": "http://127.0.0.1:8000"
        }
    },
    "change_email": {
        "title": "Confirm Email Address Change",
        "template": "emails/change_email.html",
        "context": {
            "email": "new.email@example.com",
            "confirmation_url": "http://127.0.0.1:8000/auth/confirm-change?token=sb_mock_token_change_582910",
            "site_url": "http://127.0.0.1:8000"
        }
    }
}


@router.get("", response_class=HTMLResponse)
async def email_previews_dashboard(request: Request, type: str = "verify"):
    """Renders the developer email preview studio with iframe preview, viewport toggles, and copy actions."""
    if type not in MOCK_EMAIL_DATA:
        type = "verify"
    return templates.TemplateResponse(
        request=request,
        name="dev_emails.html",
        context={
            "title": "SmallBook - Email Preview Studio",
            "active_type": type,
            "email_types": MOCK_EMAIL_DATA
        }
    )


@router.get("/render/{email_type}", response_class=HTMLResponse)
async def render_email_html(request: Request, email_type: str):
    """Renders the specified transactional email template with mock data in SmallBook light theme."""
    if email_type not in MOCK_EMAIL_DATA:
        raise HTTPException(status_code=404, detail="Unknown email template type")

    item = MOCK_EMAIL_DATA[email_type]
    ctx = {
        "request": request,
        "logo_url": "/static/images/SmallBooklogo.png",
        **item["context"]
    }
    rendered = templates.get_template(item["template"]).render(ctx)
    return HTMLResponse(content=rendered)


@router.get("/raw/{email_type}", response_class=JSONResponse)
async def get_raw_supabase_template(email_type: str):
    """Dynamically generates the raw Supabase GoTrue HTML for copy-pasting into Supabase Dashboard."""
    if email_type not in MOCK_EMAIL_DATA:
        raise HTTPException(status_code=404, detail="Unknown email template type")

    item = MOCK_EMAIL_DATA[email_type]
    gotrue_context = {
        "user_name": "",
        "email": "{{ .Email }}",
        "confirmation_url": "{{ .ConfirmationURL }}",
        "token": "{{ .Token }}",
        "site_url": "{{ .SiteURL }}",
        "logo_url": SUPABASE_PUBLIC_LOGO_URL,
    }
    content = templates.get_template(item["template"]).render(gotrue_context)

    return {
        "type": email_type,
        "title": item["title"],
        "template": item["template"],
        "html": content
    }
