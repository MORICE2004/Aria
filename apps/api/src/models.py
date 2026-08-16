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


class JobApplication(Base):
    """One job opportunity being tracked, from 'saved' to an outcome.

    Status flow (any order, user-driven):
      saved -> applied -> interview -> offer | rejected
    """

    __tablename__ = "job_applications"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_id)
    company: Mapped[str] = mapped_column(String(200))
    role: Mapped[str] = mapped_column(String(200))
    url: Mapped[str] = mapped_column(String(1000), default="")
    description: Mapped[str] = mapped_column(Text, default="")  # the job posting
    status: Mapped[str] = mapped_column(String(20), default="saved", index=True)
    notes: Mapped[str] = mapped_column(Text, default="")        # MORICE's own notes
    match_score: Mapped[int | None] = mapped_column(nullable=True)  # 0-100, from analysis
    match_notes: Mapped[str] = mapped_column(Text, default="")  # strengths/gaps summary
    cover_letter: Mapped[str] = mapped_column(Text, default="") # latest draft
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class RecruiterContact(Base):
    """A recruiter or hiring contact worth remembering."""

    __tablename__ = "recruiter_contacts"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_id)
    name: Mapped[str] = mapped_column(String(200))
    company: Mapped[str] = mapped_column(String(200), default="")
    email: Mapped[str] = mapped_column(String(320), default="")
    notes: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class Task(Base):
    """A task, reminder, or deadline. `due_at` optional; `job_id` optionally
    links it to a tracked application (e.g. an interview date)."""

    __tablename__ = "tasks"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_id)
    title: Mapped[str] = mapped_column(String(300))
    notes: Mapped[str] = mapped_column(Text, default="")
    kind: Mapped[str] = mapped_column(String(20), default="task")  # task|reminder|deadline|interview
    status: Mapped[str] = mapped_column(String(20), default="open", index=True)  # open|done
    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    job_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class LearningTopic(Base):
    """One thing MORICE is learning, with self-assessed progress.

    Status flow: learning -> comfortable -> mastered (user-driven, any order).
    The learning coach reads this list to pitch explanations at the right level.
    """

    __tablename__ = "learning_topics"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_id)
    name: Mapped[str] = mapped_column(String(200))
    status: Mapped[str] = mapped_column(String(20), default="learning", index=True)
    notes: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class Contact(Base):
    """Someone MORICE communicates with.

    `trust_level` caps what ARIA may ever do for this person, independently of
    the global autonomy mode. The effective permission is always the MORE
    RESTRICTIVE of the two — see src/whatsapp/autonomy.py.
    """

    __tablename__ = "contacts"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_id)
    name: Mapped[str] = mapped_column(String(200))
    # Channel handle (e.g. WhatsApp JID or phone). Unique per channel.
    handle: Mapped[str] = mapped_column(String(120), index=True)
    channel: Mapped[str] = mapped_column(String(30), default="whatsapp")
    # unknown | low | trusted | high | never_autonomous
    trust_level: Mapped[str] = mapped_column(String(20), default="unknown")
    # friend | colleague | boss | client | recruiter | family | academic | unknown
    relationship: Mapped[str] = mapped_column(String(30), default="unknown")
    notes: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class WhatsAppMessage(Base):
    """One observed message. ARIA stores these to learn; it never implies consent
    to reply — replying is gated by autonomy mode + trust level."""

    __tablename__ = "whatsapp_messages"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_id)
    contact_id: Mapped[str] = mapped_column(
        ForeignKey("contacts.id", ondelete="CASCADE"), index=True
    )
    # "in" = from the contact, "out" = sent by MORICE (used for style learning)
    direction: Mapped[str] = mapped_column(String(3))
    body: Mapped[str] = mapped_column(Text)
    sent_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    # True when this message came from the simulator rather than real WhatsApp.
    simulated: Mapped[bool] = mapped_column(default=False)


class MessageDraft(Base):
    """A reply ARIA prepared for MORICE to review.

    A draft is never a sent message. In suggestion mode "approved" means
    "this is good, I will send it myself" — ARIA's WhatsApp transport is
    read-only and has no send path at all.
    """

    __tablename__ = "message_drafts"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_id)
    contact_id: Mapped[str] = mapped_column(
        ForeignKey("contacts.id", ondelete="CASCADE"), index=True
    )
    # The inbound message this replies to, kept for context and audit.
    incoming: Mapped[str] = mapped_column(Text)
    draft: Mapped[str] = mapped_column(Text)
    # pending | approved | edited | rejected
    status: Mapped[str] = mapped_column(String(20), default="pending", index=True)
    final: Mapped[str] = mapped_column(Text, default="")  # what he actually used
    # Why ARIA thought this was appropriate — action explanation, not reasoning.
    rationale: Mapped[str] = mapped_column(String(400), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    decided_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class StylePattern(Base):
    """One learned fact about how MORICE writes.

    Scoped: a pattern can be global, per-relationship-type, or per-contact —
    because he does not write to his boss the way he writes to a friend.
    More specific scopes win when building a profile.

    `confidence` and `evidence_count` exist so a single message can never
    become a permanent rule. Nothing here is ever invented: statistical
    dimensions are computed from real messages, and the counts are real.
    """

    __tablename__ = "style_patterns"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_id)
    # e.g. "avg_words", "greeting", "emoji_rate", but also composite keys like
    # "edit:prefers shorter: cut 17 words to 3" and "rule:<text>". Sized for
    # those: 40 was too small and Postgres rejected the insert, while the
    # SQLite test suite silently accepted it (SQLite ignores VARCHAR limits).
    dimension: Mapped[str] = mapped_column(String(120), index=True)
    # "global" | "relationship:friend" | "contact:<id>"
    scope: Mapped[str] = mapped_column(String(60), index=True, default="global")
    value: Mapped[str] = mapped_column(Text)
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    evidence_count: Mapped[int] = mapped_column(default=0)
    # Where the evidence came from, for "why do you think that?"
    source: Mapped[str] = mapped_column(String(30), default="observed")
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class LearningEvent(Base):
    """A moment ARIA could learn from: an approval, an edit, a rejection, or
    an explicit instruction from MORICE ("never write Dear Sir/Madam").

    Kept append-only in spirit: these are the evidence behind every pattern,
    so a pattern can always be explained and audited.
    """

    __tablename__ = "learning_events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_id)
    # observed | approved | edited | rejected | rule
    kind: Mapped[str] = mapped_column(String(20), index=True)
    contact_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    draft: Mapped[str] = mapped_column(Text, default="")      # what ARIA wrote
    final: Mapped[str] = mapped_column(Text, default="")      # what MORICE used
    note: Mapped[str] = mapped_column(Text, default="")       # his explanation
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class AutonomyState(Base):
    """Singleton row holding ARIA's global autonomy mode and the kill switch.

    Exactly one row, id="singleton". Kept in the database (not memory) so the
    emergency stop survives a restart — a kill switch that forgets is not a
    kill switch.
    """

    __tablename__ = "autonomy_state"

    id: Mapped[str] = mapped_column(String(20), primary_key=True, default="singleton")
    # observe | suggest | supervised | trusted | autonomous
    mode: Mapped[str] = mapped_column(String(20), default="observe")
    emergency_stop: Mapped[bool] = mapped_column(default=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class ActionRequest(Base):
    """A sensitive action an agent WANTS to perform — pending human approval.

    Status flow:  pending -> approved -> executed | failed
                  pending -> rejected
    Nothing outward-facing ever happens except by executing an approved row.
    """

    __tablename__ = "action_requests"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_id)
    agent: Mapped[str] = mapped_column(String(50))        # who asked, e.g. "communication"
    action_type: Mapped[str] = mapped_column(String(50))  # what, e.g. "email.send"
    summary: Mapped[str] = mapped_column(String(500))     # human-readable description
    payload: Mapped[dict] = mapped_column(JSON)           # exact data to act on
    status: Mapped[str] = mapped_column(String(20), default="pending", index=True)
    result: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    decided_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class AuditEvent(Base):
    """Append-only audit log. There is deliberately NO update or delete path
    for this table anywhere in the codebase — history cannot be rewritten.
    """

    __tablename__ = "audit_events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_id)
    action_request_id: Mapped[str] = mapped_column(String(36), index=True)
    event: Mapped[str] = mapped_column(String(30))  # submitted|approved|rejected|executed|failed
    detail: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
