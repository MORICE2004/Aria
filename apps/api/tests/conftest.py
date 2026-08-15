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
from src.llm import get_router
from src.llm.base import ChatMessage, LLMProvider
from src.main import create_app
from src.memory import get_memory_service
from src.memory.embeddings import EMBEDDING_DIM, EmbeddingProvider
from src.memory.service import MemoryService


class FakeLLM(LLMProvider):
    """Predictable stand-in for Claude: echoes the last user message."""

    async def stream_chat(
        self, messages: list[ChatMessage], system: str
    ) -> AsyncIterator[str]:
        yield "Echo: "
        yield messages[-1].content


class FakeRouter:
    """Stand-in for ModelRouter: every task class resolves to FakeLLM."""

    def resolve(self, task):
        from src.llm.router import Routed, Tier

        return Routed(provider=FakeLLM(), tier=Tier.LOCAL_FAST, model="fake-model")


class FakeEmbedder(EmbeddingProvider):
    """Deterministic embeddings based on word overlap — no model download.

    Each word deterministically lights up a few vector positions, so texts
    sharing words get similar vectors. Crude, but it makes similarity search
    testable and fully predictable.
    """

    def embed(self, texts: list[str]) -> list[list[float]]:
        vectors = []
        for text in texts:
            vector = [0.0] * EMBEDDING_DIM
            for word in text.lower().split():
                vector[hash(word) % EMBEDDING_DIM] += 1.0
            vectors.append(vector)
        return vectors


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
    # Every LLM call goes through the router, so faking it here is the single
    # point that keeps the suite from reaching real Ollama/cloud providers.
    app.dependency_overrides[get_router] = lambda: FakeRouter()
    app.dependency_overrides[get_memory_service] = lambda: MemoryService(
        embedder=FakeEmbedder()
    )

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
