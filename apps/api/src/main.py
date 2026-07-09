"""ARIA API entry point.

Run locally with:  uvicorn src.main:app --reload --port 8000
Interactive API docs are auto-generated at http://localhost:8000/docs
"""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from fastapi import Depends

from src.core.config import get_settings
from src.core.logging import configure_logging
from src.core.security import require_auth
from src.db import init_db
from src.routers import (
    actions,
    auth,
    chat,
    communication,
    health,
    jobs,
    learning,
    memory,
    tasks,
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup/shutdown hooks. Before serving requests: ensure DB tables exist."""
    await init_db()
    yield

configure_logging()
logger = logging.getLogger(__name__)


def create_app() -> FastAPI:
    """Application factory.

    Building the app inside a function (instead of at import time) keeps tests
    clean — each test can create a fresh app — and gives one obvious place
    where middleware and routers are wired together.
    """
    settings = get_settings()

    app = FastAPI(
        title="ARIA API",
        description="Personal AI assistant backend — agents, memory, action gateway.",
        version="0.2.0",
        lifespan=lifespan,
    )

    # CORS: the browser blocks cross-origin requests unless the API allows them.
    # Only our own dashboard (localhost:3000 in dev) is allowed — never "*".
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:3000"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Public: health (monitoring) and auth (you must be able to log in).
    app.include_router(health.router)
    app.include_router(auth.router)
    # Protected: everything with personal data requires a valid token
    # (require_auth is a no-op while ARIA_PASSWORD is unset — dev mode).
    protected = [Depends(require_auth)]
    app.include_router(chat.router, dependencies=protected)
    app.include_router(memory.router, dependencies=protected)
    app.include_router(actions.router, dependencies=protected)
    app.include_router(communication.router, dependencies=protected)
    app.include_router(jobs.router, dependencies=protected)
    app.include_router(tasks.router, dependencies=protected)
    app.include_router(learning.router, dependencies=protected)

    logger.info("ARIA API started (env=%s)", settings.app_env)
    return app


app = create_app()
