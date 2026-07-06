"""ARIA API entry point.

Run locally with:  uvicorn src.main:app --reload --port 8000
Interactive API docs are auto-generated at http://localhost:8000/docs
"""

import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from src.core.config import get_settings
from src.core.logging import configure_logging
from src.routers import health

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
        version="0.1.0",
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

    app.include_router(health.router)

    logger.info("ARIA API started (env=%s)", settings.app_env)
    return app


app = create_app()
