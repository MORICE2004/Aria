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
    """Predictable stand-in for a real model: echoes the last user message.

    Reports token usage like a real provider so the cost-accounting path is
    exercised by the suite rather than only in production.
    """

    async def stream_chat(
        self, messages: list[ChatMessage], system: str
    ) -> AsyncIterator[str]:
        yield "Echo: "
        yield messages[-1].content
        from src.llm.base import Usage

        self.last_usage = Usage(input_tokens=10, output_tokens=5)


class FakeRouter:
    """Stand-in for ModelRouter: every task class resolves to FakeLLM.

    Accepts the optional session argument the real router uses for usage
    accounting, and records usage the same way so cost tests are meaningful.
    """

    def resolve(self, task, session=None):
        from src.llm.router import Routed, Tier, _UsageRecordingProvider

        provider = FakeLLM()
        if session is not None:
            provider = _UsageRecordingProvider(
                provider, session, ("fake", "fake-model", Tier.LOCAL_FAST.value)
            )
        return Routed(provider=provider, tier=Tier.LOCAL_FAST, model="fake-model")


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

    # Three places use the module-level SessionMaker instead of a request
    # session, because they outlive a single request: the streaming chat
    # endpoint, the queue drain, and the gateway executor that hands a message
    # to the outbound queue. Point them all at the test database — otherwise a
    # test that triggers an autonomous send would write to real Postgres.
    import src.routers.chat as chat_module
    import src.routers.whatsapp as whatsapp_module
    import src.whatsapp.sending as sending_module

    originals = {
        chat_module: chat_module.SessionMaker,
        whatsapp_module: whatsapp_module.SessionMaker,
        sending_module: sending_module.SessionMaker,
    }
    for module in originals:
        module.SessionMaker = maker

    test_client = TestClient(app, raise_server_exceptions=True)
    # Handed to tests that need to drive the queue directly rather than
    # through HTTP (outage simulation, restart recovery).
    test_client.session_maker = maker
    try:
        yield test_client
    finally:
        for module, original in originals.items():
            module.SessionMaker = original


@pytest.fixture
def ingest_secret():
    """Enable the shared-secret endpoints (ingest, outbound handover).

    Both fail closed when unset, so any test touching them needs this.
    """
    from src.core.config import get_settings

    settings = get_settings()
    before = settings.openclaw_ingest_secret
    settings.openclaw_ingest_secret = "test-ingest-secret"
    yield "test-ingest-secret"
    settings.openclaw_ingest_secret = before
