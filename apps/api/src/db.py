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
    """Bring the database schema up to date.

    On PostgreSQL this runs Alembic migrations. `create_all` used to do this
    job and was a proven liability: it creates missing TABLES but never alters
    existing ones, so a new column on an existing table was invisible to it.
    The app started fine and then returned 500 on the first query selecting
    that column — which is exactly what happened live when the autonomy engine
    added `paused` to `autonomy_state`, while the test suite stayed green
    because SQLite builds every table from scratch.

    SQLite (tests only) still uses `create_all`: the suite creates a fresh
    in-memory database per test, so there is nothing to migrate, and running
    migrations would make every test slower to solve a problem it cannot have.
    """
    from sqlalchemy import text

    from src import models  # noqa: F401  (import registers the tables on Base)

    if engine.dialect.name != "postgresql":
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        return

    async with engine.begin() as conn:
        # pgvector must exist before any migration creates a vector column.
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))

    await run_migrations()


async def run_migrations() -> None:
    """Apply any pending Alembic migrations.

    Run in a worker thread: Alembic's runner drives its own event loop, and
    calling it from inside the running one would deadlock.
    """
    import asyncio
    from pathlib import Path

    from alembic import command
    from alembic.config import Config

    api_root = Path(__file__).resolve().parents[1]

    def _upgrade() -> None:
        config = Config(str(api_root / "alembic.ini"))
        config.set_main_option("script_location", str(api_root / "migrations"))
        command.upgrade(config, "head")

    await asyncio.to_thread(_upgrade)


async def get_session() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency: one database session per request."""
    async with SessionMaker() as session:
        yield session
