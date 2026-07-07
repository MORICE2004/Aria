"""Database models (tables).

Chat history (Phase 1):
  Conversation 1 ── * Message
Semantic memory (Phase 2):
  MemoryItem 1 ── * MemoryChunk   (each chunk carries an embedding vector)
"""

import uuid
from datetime import datetime, timezone

from pgvector.sqlalchemy import Vector
from sqlalchemy import JSON, DateTime, Float, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import TypeDecorator

from src.db import Base
from src.memory.embeddings import EMBEDDING_DIM


class EmbeddingColumn(TypeDecorator):
    """Vector column that adapts to the database.

    PostgreSQL gets a real pgvector column (similarity search happens in the
    database). SQLite — used only by tests — stores the vector as JSON.
    """

    impl = JSON
    cache_ok = True

    def load_dialect_impl(self, dialect):
        if dialect.name == "postgresql":
            return dialect.type_descriptor(Vector(EMBEDDING_DIM))
        return dialect.type_descriptor(JSON())

    class Comparator(TypeDecorator.Comparator):
        """Re-expose pgvector's cosine_distance on the wrapped column.

        `<=>` is pgvector's cosine-distance operator; the query vector is
        bound through this column's type, so it is serialized correctly.
        """

        def cosine_distance(self, other):
            return self.op("<=>", return_type=Float)(other)

    comparator_factory = Comparator


def _now() -> datetime:
    """Timezone-aware UTC timestamp (naive datetimes cause subtle bugs)."""
    return datetime.now(timezone.utc)


def _new_id() -> str:
    """Random UUID as a string — safe to expose in URLs, unlike counters."""
    return str(uuid.uuid4())


class Conversation(Base):
    __tablename__ = "conversations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_id)
    title: Mapped[str] = mapped_column(String(200), default="New conversation")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    # cascade: deleting a conversation deletes its messages too — no orphans.
    messages: Mapped[list["Message"]] = relationship(
        back_populates="conversation",
        cascade="all, delete-orphan",
        order_by="Message.created_at",
    )


class Message(Base):
    __tablename__ = "messages"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_id)
    conversation_id: Mapped[str] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE"), index=True
    )
    role: Mapped[str] = mapped_column(String(20))  # "user" | "assistant"
    content: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    conversation: Mapped[Conversation] = relationship(back_populates="messages")


class MemoryItem(Base):
    """One remembered thing: a note, a document, a fact, or a writing sample."""

    __tablename__ = "memory_items"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_id)
    title: Mapped[str] = mapped_column(String(200))
    kind: Mapped[str] = mapped_column(String(20))  # "note" | "document" | "fact" | "style"
    content: Mapped[str] = mapped_column(Text)     # full original text
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    chunks: Mapped[list["MemoryChunk"]] = relationship(
        back_populates="item", cascade="all, delete-orphan"
    )


class MemoryChunk(Base):
    """A searchable piece of a MemoryItem, with its embedding vector."""

    __tablename__ = "memory_chunks"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_id)
    item_id: Mapped[str] = mapped_column(
        ForeignKey("memory_items.id", ondelete="CASCADE"), index=True
    )
    content: Mapped[str] = mapped_column(Text)
    embedding: Mapped[list[float]] = mapped_column(EmbeddingColumn)

    item: Mapped[MemoryItem] = relationship(back_populates="chunks")
