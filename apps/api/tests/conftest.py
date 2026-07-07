"""Shared test fixtures.

Two substitutions make the suite fast, free, and self-contained:
  1. The database is swapped for in-memory SQLite — no Postgres needed.
  2. The LLM is swapped for a fake that replies instantly — no API key,
     no cost, fully predictable output.

Both use FastAPI's dependency_overrides: the app code is untouched; only
what gets injected changes. This is the payoff of dependency injection.
"""

from collections.abc import AsyncIterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from src.db import Base, get_session
from src.llm import get_llm_provider
from src.llm.base import ChatMessage, LLMProvider
from src.main import create_app


class FakeLLM(LLMProvider):
    """Predictable stand-in for Claude: echoes the last user message."""

    async def stream_chat(
        self, messages: list[ChatMessage], system: str
    ) -> AsyncIterator[str]:
        yield "Echo: "
        yield messages[-1].content


@pytest.fixture
def client() -> TestClient:
    # StaticPool keeps ONE in-memory SQLite connection alive for the whole
    # test; without it each session would get a fresh, empty database.
    engine = create_async_engine(
        "sqlite+aiosqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    maker = async_sessionmaker(engine, expire_on_commit=False)

    async def override_session():
        async with maker() as session:
            yield session

    app = create_app()
    app.dependency_overrides[get_session] = override_session
    app.dependency_overrides[get_llm_provider] = lambda: FakeLLM()

    # Create the tables in the test database. (We deliberately do NOT enter
    # the app's lifespan — that would call init_db() against the real
    # Postgres. TestClient only runs lifespan when used as a context manager.)
    import asyncio

    async def _create() -> None:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    asyncio.run(_create())

    # The streaming endpoint persists the reply via the module-level
    # SessionMaker; point it at the test database too, and restore after.
    import src.routers.chat as chat_module

    original_maker = chat_module.SessionMaker
    chat_module.SessionMaker = maker
    try:
        yield TestClient(app, raise_server_exceptions=True)
    finally:
        chat_module.SessionMaker = original_maker
