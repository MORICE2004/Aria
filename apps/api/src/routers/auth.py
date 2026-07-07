"""Auth endpoints: login and auth status."""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from src.core.config import get_settings
from src.core.security import create_token, password_matches

router = APIRouter(prefix="/auth", tags=["auth"])


class LoginIn(BaseModel):
    password: str


class TokenOut(BaseModel):
    token: str


class StatusOut(BaseModel):
    auth_enabled: bool


@router.get("/status", response_model=StatusOut)
def auth_status() -> StatusOut:
    """Tells the frontend whether a login screen is needed."""
    return StatusOut(auth_enabled=bool(get_settings().aria_password))


@router.post("/login", response_model=TokenOut)
def login(body: LoginIn) -> TokenOut:
    if not get_settings().aria_password:
        raise HTTPException(400, "Auth is disabled (no ARIA_PASSWORD set)")
    if not password_matches(body.password):
        # Same vague message for any failure — don't help someone guessing.
        raise HTTPException(401, "Login failed")
    return TokenOut(token=create_token())
