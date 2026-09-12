"""
Authentication Domain Schemas

Defines Pydantic request and response schemas for user authentication workflows,
including credential sign-in, account registration, password reset requests,
and authenticated password update procedures handled through Supabase Auth (GoTrue).
"""

from typing import Optional
from pydantic import BaseModel, EmailStr


class SignInSchema(BaseModel):
    """
    User Sign-In Request Payload.

    Validates login credentials submitted to `/auth/api/sign-in`.
    """
    email: EmailStr
    password: str


class SignUpSchema(BaseModel):
    """
    User Registration Request Payload.

    Validates new account creation parameters submitted to `/auth/api/sign-up`.
    """
    email: EmailStr
    password: str
    fullname: Optional[str] = None


class ForgotPasswordSchema(BaseModel):
    """
    Password Recovery Dispatch Payload.

    Validates the target email address for sending password reset / verification links.
    """
    email: EmailStr


class UpdatePasswordSchema(BaseModel):
    """
    Password Update / Reset Finalization Payload.

    Carries the temporary recovery access token and the newly chosen password
    to update the user's Supabase GoTrue authentication credentials.
    """
    access_token: str
    password: str
    refresh_token: Optional[str] = ""

