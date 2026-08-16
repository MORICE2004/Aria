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


# Columns added to tables that already existed in a live database.
#
# `create_all` creates missing TABLES but never alters existing ones, so a new
# column on an existing table is invisible to it — the app starts fine and then
# returns 500 on the first query that selects the column. That is exactly what
# happened when the autonomy engine added `paused` to `autonomy_state`: the
# tests passed (SQLite builds every table from scratch) and the live API broke.
#
# This is a stopgap, and deliberately a boring one: additive columns only, no
# renames, no drops, no data migration. The moment a change needs more than
# this, it needs Alembic instead — see docs/ARIA_CURRENT_STATE.md §15.
_ADDED_COLUMNS: list[tuple[str, str, str]] = [
    ("autonomy_state", "paused", "BOOLEAN NOT NULL DEFAULT FALSE"),
    ("autonomy_state", "autonomy_stopped", "BOOLEAN NOT NULL DEFAULT FALSE"),
    ("contacts", "autonomy_enabled", "BOOLEAN NOT NULL DEFAULT FALSE"),
    ("contacts", "allowed_actions", "JSON"),
    ("contacts", "forbidden_actions", "JSON"),
    ("contacts", "paused", "BOOLEAN NOT NULL DEFAULT FALSE"),
    ("contacts", "taken_over", "BOOLEAN NOT NULL DEFAULT FALSE"),
    ("contacts", "taken_over_at", "TIMESTAMPTZ"),
]


async def init_db() -> None:
    """Create missing tables, then add missing columns to existing ones."""
    from sqlalchemy import text

    from src import models  # noqa: F401  (import registers the tables on Base)

    async with engine.begin() as conn:
        if conn.dialect.name == "postgresql":
            # Enable pgvector before creating tables that use vector columns.
            await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        await conn.run_sync(Base.metadata.create_all)

        if conn.dialect.name == "postgresql":
            # IF NOT EXISTS makes this idempotent, so it is safe on every boot.
            for table, column, definition in _ADDED_COLUMNS:
                await conn.execute(
                    text(
                        f"ALTER TABLE {table} "
                        f"ADD COLUMN IF NOT EXISTS {column} {definition}"
                    )
                )


async def get_session() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency: one database session per request."""
    async with SessionMaker() as session:
        yield session
