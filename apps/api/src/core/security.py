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

import secrets
from datetime import datetime, timedelta, timezone

import jwt
from fastapi import HTTPException, Request

from src.core.config import get_settings

TOKEN_LIFETIME = timedelta(days=7)
ALGORITHM = "HS256"


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
