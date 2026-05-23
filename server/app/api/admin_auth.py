"""POST /api/auth/login — issue JWT for the admin UI."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ..auth_admin import (
    admin_auth_configured,
    create_admin_token,
    verify_admin_login,
)

router = APIRouter(prefix="/api/auth", tags=["auth"])


class LoginIn(BaseModel):
    username: str
    password: str


class LoginOut(BaseModel):
    access_token: str
    token_type: str = "bearer"


class AuthStatusOut(BaseModel):
    configured: bool


@router.get("/status", response_model=AuthStatusOut)
def auth_status() -> AuthStatusOut:
    return AuthStatusOut(configured=admin_auth_configured())


@router.post("/login", response_model=LoginOut)
def login(body: LoginIn) -> LoginOut:
    if not admin_auth_configured():
        raise HTTPException(
            503,
            "Admin auth is not configured. Set ADMIN_USERNAME, ADMIN_PASSWORD, "
            "and ADMIN_JWT_SECRET on the server.",
        )
    if not verify_admin_login(body.username, body.password):
        raise HTTPException(401, "Invalid username or password")
    return LoginOut(access_token=create_admin_token(body.username))
