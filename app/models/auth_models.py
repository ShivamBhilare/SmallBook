from typing import Optional
from pydantic import BaseModel, EmailStr


class SignInSchema(BaseModel):
    email: EmailStr
    password: str


class SignUpSchema(BaseModel):
    email: EmailStr
    password: str
    fullname: Optional[str] = None


class ForgotPasswordSchema(BaseModel):
    email: EmailStr


class UpdatePasswordSchema(BaseModel):
    access_token: str
    password: str
    refresh_token: Optional[str] = ""
