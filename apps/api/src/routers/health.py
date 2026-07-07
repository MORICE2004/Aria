"""Health endpoints.

`/health` answers "is the API process alive?" — used by the dashboard, Docker
healthchecks, and later by monitoring. Phase 1 will extend it to also check
the database and Redis connections.
"""

from fastapi import APIRouter
from pydantic import BaseModel

from src.core.config import get_settings

router = APIRouter(tags=["health"])


class HealthResponse(BaseModel):
    """Shape of the health check response (validated + shown in /docs)."""

    status: str
    env: str
    version: str


@router.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    """Report that the API is up."""
    return HealthResponse(status="ok", env=get_settings().app_env, version="0.2.0")
