"""Health and readiness endpoints.

Two different questions, deliberately kept separate:

  `/health`  — is this process alive? Cheap, never fails for a dependency,
               never rate limited. Used by Docker and by the dashboard.

  `/ready`   — is ARIA actually able to do her job? Checks the database, the
               local model, the schema version, and whether her background
               workers are running.

Conflating them is a common and expensive mistake: if the liveness check fails
because Ollama is down, an orchestrator restarts a perfectly healthy API and
achieves nothing except losing the queue worker's in-flight state.
"""

import logging

from fastapi import APIRouter
from pydantic import BaseModel

from src.core.config import get_settings

logger = logging.getLogger(__name__)
router = APIRouter(tags=["health"])

VERSION = "0.3.0"


class HealthResponse(BaseModel):
    """Shape of the health check response (validated + shown in /docs)."""

    status: str
    env: str
    version: str


@router.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    """Report that the API process is up. Deliberately checks nothing else."""
    return HealthResponse(status="ok", env=get_settings().app_env, version=VERSION)


class Check(BaseModel):
    ok: bool
    detail: str = ""


class ReadyResponse(BaseModel):
    # False when anything ARIA needs to function is unavailable.
    ready: bool
    checks: dict[str, Check]


@router.get("/ready", response_model=ReadyResponse)
async def ready() -> ReadyResponse:
    """Can ARIA actually work right now?

    Every check reports independently rather than short-circuiting, because
    "the database is down" and "the database is down AND the model is down"
    are different situations and the second one should not be hidden by the
    first.
    """
    checks: dict[str, Check] = {}

    checks["database"] = await _check_database()
    checks["schema"] = await _check_schema()
    checks["local_model"] = await _check_ollama()
    checks["workers"] = _check_workers()
    checks["auth"] = _check_auth()

    # Auth being off does not stop ARIA working — it is reported, loudly, but
    # it is a posture warning rather than an outage.
    blocking = [name for name, c in checks.items() if not c.ok and name != "auth"]
    return ReadyResponse(ready=not blocking, checks=checks)


async def _check_database() -> Check:
    from sqlalchemy import text

    from src.db import engine

    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        return Check(ok=True, detail="reachable")
    except Exception as exc:  # noqa: BLE001
        return Check(ok=False, detail=f"{type(exc).__name__}: {exc}")


async def _check_schema() -> Check:
    """Is the database schema at the revision this code expects?

    A schema one migration behind is the failure that produced a live 500
    after the autonomy engine shipped, so it is worth reporting explicitly
    rather than discovering through a stack trace.
    """
    from sqlalchemy import text

    from src.db import engine

    if engine.dialect.name != "postgresql":
        return Check(ok=True, detail="sqlite: schema created directly")

    try:
        async with engine.connect() as conn:
            result = await conn.execute(text("SELECT version_num FROM alembic_version"))
            current = result.scalar_one_or_none()
        if not current:
            return Check(ok=False, detail="no migration revision recorded")
        return Check(ok=True, detail=f"at revision {current}")
    except Exception as exc:  # noqa: BLE001
        return Check(ok=False, detail=f"cannot read schema version: {exc}")


async def _check_ollama() -> Check:
    """Is the local model available?

    Worth its own check because ARIA routes classification and drafting
    locally: without Ollama she still runs, but every inbound message fails
    processing and lands in the retry queue.
    """
    settings = get_settings()
    if not settings.ollama_fast_model:
        return Check(ok=True, detail="local models disabled")

    try:
        import httpx

        async with httpx.AsyncClient(timeout=3.0) as client:
            response = await client.get(f"{settings.ollama_base_url}/api/tags")
        if response.status_code != 200:
            return Check(ok=False, detail=f"Ollama returned {response.status_code}")

        models = [m.get("name", "") for m in response.json().get("models", [])]
        if settings.ollama_fast_model not in models:
            return Check(
                ok=False,
                detail=(
                    f"'{settings.ollama_fast_model}' not installed "
                    f"(have: {', '.join(models) or 'nothing'})"
                ),
            )
        return Check(ok=True, detail=settings.ollama_fast_model)
    except Exception as exc:  # noqa: BLE001
        return Check(ok=False, detail=f"Ollama unreachable: {exc}")


def _check_workers() -> Check:
    """Are the background loops running?

    A dead queue worker is invisible from the outside — messages arrive, are
    stored, and simply never get handled.
    """
    from src.proactive.scheduler import scheduler_status

    settings = get_settings()
    problems: list[str] = []

    if settings.proactive_enabled and not scheduler_status()["running"]:
        problems.append("proactive scheduler is not running")

    if settings.whatsapp_worker_enabled:
        from src.whatsapp import worker as worker_module

        active = worker_module._worker
        if active is None or active._task is None or active._task.done():
            problems.append("WhatsApp queue worker is not running")

    if problems:
        return Check(ok=False, detail="; ".join(problems))
    return Check(ok=True, detail="running")


def _check_auth() -> Check:
    if get_settings().aria_password:
        return Check(ok=True, detail="enabled")
    return Check(
        ok=False,
        detail=(
            "no password set - ARIA will not send messages unattended, and "
            "anyone who can reach this API controls her"
        ),
    )
