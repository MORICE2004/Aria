"""Authentication: single-user password login issuing JWTs.

How it works:
  1. POST /auth/login with the password from .env (ARIA_PASSWORD).
  2. The API returns a JWT — a signed, expiring token. "Signed" means it
     cannot be forged or altered without SECRET_KEY; the server can trust it
     without storing sessions.
  3. The frontend sends it on every request: `Authorization: Bearer <token>`.

If ARIA_PASSWORD is empty, auth is disabled — sensible while everything runs
on localhost only. It becomes mandatory the moment ARIA is exposed anywhere.
"""

import logging
import secrets
from datetime import datetime, timedelta, timezone

import jwt
from fastapi import HTTPException, Request

from src.core.config import get_settings

logger = logging.getLogger(__name__)

TOKEN_LIFETIME = timedelta(days=7)
ALGORITHM = "HS256"

# The value shipped in .env.example. A token signed with it is forgeable by
# anyone who has read this repository, so it must never protect real data.
DEFAULT_SECRET_KEY = "dev-only-secret-change-me"

# HS256 keys shorter than this are brute-forceable offline once someone holds
# a single token.
MIN_SECRET_KEY_LENGTH = 32


class InsecureConfiguration(RuntimeError):
    """Startup refused: the configuration would provide false security."""


def check_startup_security() -> list[str]:
    """Validate security configuration at boot. Returns warnings; raises on
    combinations that would be actively misleading.

    The distinction being drawn: running without auth is a *choice* (fine on
    a laptop, logged loudly). Running WITH auth that does not actually protect
    anything is a *lie*, and ARIA refuses to tell it.
    """
    settings = get_settings()
    warnings: list[str] = []

    if not settings.aria_password:
        warnings.append(
            "AUTH IS DISABLED (ARIA_PASSWORD is empty). Anyone who can reach "
            "this API has full control of ARIA, including her memory and her "
            "autonomy settings. Safe on localhost; not safe on a network."
        )
        return warnings

    # Auth is on, so the things auth depends on must be real.
    if settings.secret_key == DEFAULT_SECRET_KEY:
        raise InsecureConfiguration(
            "ARIA_PASSWORD is set but SECRET_KEY is still the example value. "
            "Tokens signed with it can be forged by anyone who has read this "
            "repository, so login would provide the appearance of security "
            "and none of the substance. Set SECRET_KEY in .env to a long "
            "random string."
        )
    if len(settings.secret_key) < MIN_SECRET_KEY_LENGTH:
        raise InsecureConfiguration(
            f"SECRET_KEY is {len(settings.secret_key)} characters. Use at "
            f"least {MIN_SECRET_KEY_LENGTH}: a short HS256 key can be brute "
            "forced offline from a single captured token."
        )
    if len(settings.aria_password) < 12:
        warnings.append(
            "ARIA_PASSWORD is short. It is the only thing between the "
            "internet and everything ARIA knows about you."
        )

    return warnings


def password_matches(candidate: str) -> bool:
    """Constant-time comparison — normal `==` leaks timing information."""
    return secrets.compare_digest(candidate, get_settings().aria_password)


def create_token() -> str:
    expires = datetime.now(timezone.utc) + TOKEN_LIFETIME
    return jwt.encode(
        {"sub": "morice", "exp": expires}, get_settings().secret_key, algorithm=ALGORITHM
    )


def require_auth(request: Request) -> None:
    """FastAPI dependency protecting a router. No-op when auth is disabled."""
    if not get_settings().aria_password:
        return  # auth disabled (dev mode)

    header = request.headers.get("Authorization", "")
    if not header.startswith("Bearer "):
        raise HTTPException(401, "Not authenticated")
    try:
        jwt.decode(header[7:], get_settings().secret_key, algorithms=[ALGORITHM])
    except jwt.PyJWTError as exc:
        raise HTTPException(401, "Invalid or expired token") from exc
