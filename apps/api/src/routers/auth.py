"""Auth endpoints: login and auth status.

Login is the one endpoint an attacker can attack without already having
access, so it is the one place worth defending carefully: constant-time
comparison, rate limiting, progressive lockout, and identical error messages
for every kind of failure.
"""

import logging

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from src.core.config import get_settings
from src.core.ratelimit import client_key, login_limiter, login_lockout
from src.core.security import create_token, password_matches

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["auth"])


class LoginIn(BaseModel):
    password: str


class TokenOut(BaseModel):
    token: str


class StatusOut(BaseModel):
    auth_enabled: bool
    # Surfaced so the dashboard can show an honest banner instead of letting
    # an unprotected ARIA look identical to a protected one.
    warning: str = ""


@router.get("/status", response_model=StatusOut)
def auth_status() -> StatusOut:
    """Tells the frontend whether a login screen is needed."""
    enabled = bool(get_settings().aria_password)
    return StatusOut(
        auth_enabled=enabled,
        warning=""
        if enabled
        else (
            "Auth is disabled. Anyone who can reach this API controls ARIA. "
            "Set ARIA_PASSWORD in .env before using her on a network."
        ),
    )


@router.post("/login", response_model=TokenOut)
def login(body: LoginIn, request: Request) -> TokenOut:
    if not get_settings().aria_password:
        raise HTTPException(400, "Auth is disabled (no ARIA_PASSWORD set)")

    caller = client_key(request)

    locked = login_lockout.locked_for(caller)
    if locked > 0:
        raise HTTPException(
            429,
            f"Too many failed attempts. Try again in {int(locked)} seconds.",
            headers={"Retry-After": str(int(locked))},
        )

    allowed, retry_after = login_limiter.check(caller)
    if not allowed:
        raise HTTPException(
            429,
            "Too many login attempts.",
            headers={"Retry-After": str(int(retry_after) or 1)},
        )

    if not password_matches(body.password):
        penalty = login_lockout.record_failure(caller)
        # Logged because repeated failures from an unexpected address are the
        # earliest signal MORICE would get that someone is probing ARIA.
        logger.warning(
            "Failed login from %s%s",
            caller,
            f" — locked out for {int(penalty)}s" if penalty else "",
        )
        # Same vague message for any failure — don't help someone guessing.
        raise HTTPException(401, "Login failed")

    login_lockout.record_success(caller)
    return TokenOut(token=create_token())
