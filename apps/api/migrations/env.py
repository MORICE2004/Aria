"""Alembic environment.

Two deliberate departures from the generated template:

1. **The database URL comes from ARIA's settings, not alembic.ini.** There is
   already exactly one place that reads the environment (`core/config.py`),
   and a second source of truth for the connection string is how you end up
   migrating the wrong database.

2. **pgvector is imported for its side effect.** Autogenerate needs the
   `vector` type registered or it renders `memory_chunks.embedding` as an
   unknown type and proposes dropping it — which would silently delete every
   embedding ARIA has.
"""

import asyncio
from logging.config import fileConfig

from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

from alembic import context

# Registers the pgvector type with SQLAlchemy. Without this import,
# autogenerate does not recognise the embedding column.
import pgvector.sqlalchemy  # noqa: F401

from src.core.config import get_settings
from src.db import Base
from src import models  # noqa: F401 — importing registers every table on Base

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# One source of truth for where ARIA's data lives.
config.set_main_option("sqlalchemy.url", get_settings().database_url)

target_metadata = Base.metadata


def _include_object(object_, name, type_, reflected, compare_to):
    """Keep autogenerate focused on ARIA's own tables.

    Without this, an extension-owned table in the same schema shows up as
    something Alembic wants to drop.
    """
    if type_ == "table" and name in {"alembic_version"}:
        return False
    return True


def run_migrations_offline() -> None:
    """Emit SQL to stdout instead of running it — useful for review."""
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        include_object=_include_object,
        # Detect column type changes, not just added/removed columns.
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        include_object=_include_object,
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


def run_migrations_online() -> None:
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
