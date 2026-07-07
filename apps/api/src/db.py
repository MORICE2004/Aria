"""Database setup (SQLAlchemy, async).

One engine for the whole app. Request handlers get a session through the
`get_session` dependency — FastAPI opens it per request and closes it after,
so sessions are never leaked or shared between requests.
"""

from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from src.core.config import get_settings


class Base(DeclarativeBase):
    """Parent class for all database models (tables)."""


engine = create_async_engine(get_settings().database_url, echo=False)

# expire_on_commit=False: objects stay usable after commit (needed for async).
SessionMaker = async_sessionmaker(engine, expire_on_commit=False)


async def init_db() -> None:
    """Create any missing tables at startup.

    Fine for a personal project at this stage; when the schema starts
    evolving we will switch to real migrations (Alembic).
    """
    from sqlalchemy import text

    from src import models  # noqa: F401  (import registers the tables on Base)

    async with engine.begin() as conn:
        if conn.dialect.name == "postgresql":
            # Enable pgvector before creating tables that use vector columns.
            await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        await conn.run_sync(Base.metadata.create_all)


async def get_session() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency: one database session per request."""
    async with SessionMaker() as session:
        yield session
