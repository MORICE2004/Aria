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
    """One remembered thing.

    `kind` is WHAT it is (note/document/fact/style). `memory_type` is HOW it
    should behave — whether it is durable personal knowledge, a passing
    detail, or a project fact that expires when the project ends. Those are
    different questions, so they are different columns.

    `provenance` answers "why do you remember that?" — the single most
    important field for trusting a memory system.
    """

    __tablename__ = "memory_items"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_id)
    title: Mapped[str] = mapped_column(String(200))
    kind: Mapped[str] = mapped_column(String(20))  # "note" | "document" | "fact" | "style"
    content: Mapped[str] = mapped_column(Text)     # full original text
    # longterm | preference | project | relationship | episodic | transient
    memory_type: Mapped[str] = mapped_column(String(20), default="longterm", index=True)
    # 0-1: how much this deserves to persist. Low-scoring memories are
    # retrieved last and are the first suggested for cleanup.
    importance: Mapped[float] = mapped_column(Float, default=0.5)
    # Where it came from, in MORICE's terms: "you told me", "from your CV",
    # "extracted from a WhatsApp message on 2026-08-16".
    provenance: Mapped[str] = mapped_column(String(300), default="")
    # Transient memories expire; everything else has no expiry.
    expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_used_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    use_count: Mapped[int] = mapped_column(default=0)
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

    Autonomy for a contact requires TWO separate switches: a trust level that
    permits it, and `autonomy_enabled` set deliberately. Trust describes the
    relationship; `autonomy_enabled` is the explicit grant. Keeping them apart
    means raising trust — a natural thing to do as ARIA learns someone — can
    never by itself start sending messages to them.
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

    # --- autonomy, per contact ---
    # The explicit grant. Default false: no contact is autonomous by accident.
    autonomy_enabled: Mapped[bool] = mapped_column(default=False)
    # Action types ARIA may handle autonomously for this person, JSON list.
    # Empty means "the conservative default", not "everything".
    allowed_actions: Mapped[list] = mapped_column(JSON, default=list)
    # Explicitly forbidden action types. Always wins over allowed_actions.
    forbidden_actions: Mapped[list] = mapped_column(JSON, default=list)
    # Per-contact off switch — silence ARIA for one person without touching
    # anyone else, and without disabling her globally.
    paused: Mapped[bool] = mapped_column(default=False)
    # MORICE is handling this conversation himself right now. ARIA stays out
    # until this is explicitly cleared.
    taken_over: Mapped[bool] = mapped_column(default=False)
    taken_over_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
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


class InboundMessage(Base):
    """A received message, persisted BEFORE anything tries to understand it.

    This table is the reason a WhatsApp message cannot be lost. The ingest
    endpoint's only job is to durably write a row here and commit; every
    expensive, failure-prone step (classification, drafting, deciding, sending)
    happens afterwards and is retryable. If the API dies mid-processing, the
    row is still `pending` or `processing` and is picked up again on restart.

    `dedupe_key` is the WhatsApp message id. It carries a UNIQUE constraint,
    which is what makes redelivery safe: the bridge may send the same message
    any number of times, and the second insert is rejected by the database
    rather than by hopeful application logic.

    Status flow:
        pending -> processing -> done
                              -> pending (retry, with backoff)
                              -> dead    (attempts exhausted; needs a human)
    """

    __tablename__ = "inbound_messages"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_id)
    # Stable per-message identity from the transport. Unique: the whole point.
    dedupe_key: Mapped[str] = mapped_column(String(200), unique=True, index=True)
    channel: Mapped[str] = mapped_column(String(30), default="whatsapp")
    handle: Mapped[str] = mapped_column(String(120), index=True)
    name: Mapped[str] = mapped_column(String(200), default="")
    body: Mapped[str] = mapped_column(Text)
    direction: Mapped[str] = mapped_column(String(3), default="in")
    simulated: Mapped[bool] = mapped_column(default=False)
    # When the sender sent it (transport clock) vs when ARIA received it.
    # Both are kept so a delayed message is recognisable as delayed.
    sent_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, index=True
    )

    # pending | processing | done | dead
    status: Mapped[str] = mapped_column(String(20), default="pending", index=True)
    attempts: Mapped[int] = mapped_column(default=0)
    # Earliest time a retry may run. Backoff is expressed as a timestamp rather
    # than a sleep, so it survives a restart like everything else here.
    next_attempt_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, index=True
    )
    last_error: Mapped[str] = mapped_column(Text, default="")
    # Set when a worker claims the row; used to reclaim rows abandoned by a
    # process that died while holding them.
    claimed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    processed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # Short human-readable outcome, e.g. "observed; decision=suggest".
    outcome: Mapped[str] = mapped_column(String(300), default="")


class ModelUsage(Base):
    """One LLM call: what ran where, and what it plausibly cost.

    Token counts are FACTS reported by the provider. `estimated_cost_usd` is
    exactly that — an estimate from a configurable price table, and it is
    labelled as such everywhere it is shown. Local calls are 0.0, which is
    the one cost figure that is certain.
    """

    __tablename__ = "model_usage"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_id)
    provider: Mapped[str] = mapped_column(String(30), index=True)  # ollama|gemini|...
    model: Mapped[str] = mapped_column(String(60))
    task_class: Mapped[str] = mapped_column(String(20), default="")  # routine|converse|reason
    tier: Mapped[str] = mapped_column(String(20), default="")        # local_fast|cloud|...
    input_tokens: Mapped[int] = mapped_column(default=0)
    output_tokens: Mapped[int] = mapped_column(default=0)
    estimated_cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, index=True
    )


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
    """Singleton row holding ARIA's global autonomy mode and the stop controls.

    Exactly one row, id="singleton". Kept in the database (not memory) so the
    emergency stop survives a restart — a kill switch that forgets is not a
    kill switch.

    Three separate stops, because they mean different things and MORICE will
    want different ones at different moments:

      `paused`         — ARIA stops acting but keeps observing and learning.
                         The everyday "not now".
      `autonomy_stopped` — no automatic sending; drafting and asking continue.
                         The "keep helping, but check with me".
      `emergency_stop` — everything outward stops and the mode drops to
                         observe. The "stop, now".
    """

    __tablename__ = "autonomy_state"

    id: Mapped[str] = mapped_column(String(20), primary_key=True, default="singleton")
    # observe | suggest | supervised | limited_autonomy | full_autonomy
    mode: Mapped[str] = mapped_column(String(20), default="observe")
    emergency_stop: Mapped[bool] = mapped_column(default=False)
    paused: Mapped[bool] = mapped_column(default=False)
    autonomy_stopped: Mapped[bool] = mapped_column(default=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class AutonomousResponse(Base):
    """One reply ARIA sent on her own, with everything needed to judge it later.

    Recorded whether or not MORICE ever looks at it. The point is that an
    autonomous action is never invisible: months later it must be possible to
    ask "why did she send that?" and get a complete answer — which contact,
    which policy, which model, how confident, how risky, and what happened
    afterwards.

    On the learning fields, note what is deliberately NOT here: any field
    meaning "assumed correct because MORICE said nothing". Silence is not
    approval. `user_reaction` stays "none" until he actually reacts, and the
    learning code treats "none" as the absence of evidence rather than as
    weak positive evidence.
    """

    __tablename__ = "autonomous_responses"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_id)
    contact_id: Mapped[str] = mapped_column(
        ForeignKey("contacts.id", ondelete="CASCADE"), index=True
    )
    inbound_message_id: Mapped[str | None] = mapped_column(String(36), nullable=True)

    incoming: Mapped[str] = mapped_column(Text)
    response: Mapped[str] = mapped_column(Text)

    # --- why ARIA thought this was allowed ---
    decision: Mapped[str] = mapped_column(String(20), index=True)  # auto_send|...
    decision_reasons: Mapped[list] = mapped_column(JSON, default=list)
    autonomy_mode: Mapped[str] = mapped_column(String(30), default="")
    action_type: Mapped[str] = mapped_column(String(30), default="")
    risk_level: Mapped[str] = mapped_column(String(20), default="", index=True)
    risk_categories: Mapped[list] = mapped_column(JSON, default=list)
    communication_confidence: Mapped[float] = mapped_column(Float, default=0.0)
    readiness_score: Mapped[float] = mapped_column(Float, default=0.0)

    # --- how it was produced ---
    model: Mapped[str] = mapped_column(String(60), default="")
    provider: Mapped[str] = mapped_column(String(30), default="")
    estimated_cost_usd: Mapped[float] = mapped_column(Float, default=0.0)

    # --- what happened to it ---
    # queued | sent | failed | blocked
    send_status: Mapped[str] = mapped_column(String(20), default="queued", index=True)
    send_error: Mapped[str] = mapped_column(Text, default="")
    action_request_id: Mapped[str | None] = mapped_column(String(36), nullable=True)

    # --- what MORICE thought, IF he said anything ---
    # none | approved | corrected | rejected. "none" means no evidence, and is
    # never interpreted as approval.
    user_reaction: Mapped[str] = mapped_column(String(20), default="none", index=True)
    correction: Mapped[str] = mapped_column(Text, default="")
    reacted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # Lessons this response generated, for the transparency view.
    learning_event_ids: Mapped[list] = mapped_column(JSON, default=list)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, index=True
    )


class OutboundMessage(Base):
    """A message approved for sending, waiting for the bridge to collect it.

    ARIA's API never talks to WhatsApp directly. It writes a row here only
    after the Action Gateway has executed an approved request, and a separate
    sender process collects it. That indirection is deliberate: the process
    holding the WhatsApp session has no reasoning in it and no ability to
    decide anything, and the process that reasons has no socket to WhatsApp.
    Neither one can send a message alone.

    Collection re-checks the kill switch, so a message approved a minute ago
    still cannot go out if MORICE has since pressed stop.
    """

    __tablename__ = "outbound_messages"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_id)
    contact_id: Mapped[str] = mapped_column(
        ForeignKey("contacts.id", ondelete="CASCADE"), index=True
    )
    handle: Mapped[str] = mapped_column(String(120), index=True)
    body: Mapped[str] = mapped_column(Text)
    # Where it came from: autonomous | approved_draft | manual
    origin: Mapped[str] = mapped_column(String(20), default="autonomous")
    autonomous_response_id: Mapped[str | None] = mapped_column(
        String(36), nullable=True
    )
    action_request_id: Mapped[str] = mapped_column(String(36), default="")
    # pending | claimed | sent | failed | cancelled
    status: Mapped[str] = mapped_column(String(20), default="pending", index=True)
    attempts: Mapped[int] = mapped_column(default=0)
    last_error: Mapped[str] = mapped_column(Text, default="")
    claimed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    sent_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, index=True
    )


class Document(Base):
    """A file MORICE uploaded, and the text ARIA read out of it.

    The full text is kept alongside the memory item rather than only in
    chunks: chunks are optimised for retrieval, and answering "what does the
    contract say about notice periods" sometimes needs the surrounding
    paragraph that chunking split away.
    """

    __tablename__ = "documents"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_id)
    filename: Mapped[str] = mapped_column(String(300))
    format: Mapped[str] = mapped_column(String(20))  # pdf | txt | md | csv | json
    pages: Mapped[int] = mapped_column(default=0)
    characters: Mapped[int] = mapped_column(default=0)
    sections: Mapped[list] = mapped_column(JSON, default=list)
    content: Mapped[str] = mapped_column(Text)
    # The searchable copy in semantic memory.
    memory_item_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    facts_extracted: Mapped[bool] = mapped_column(default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, index=True
    )

    facts: Mapped[list["DocumentFact"]] = relationship(
        back_populates="document", cascade="all, delete-orphan"
    )


class DocumentFact(Base):
    """Something a model claims a document states.

    A PROPOSAL, not a belief. It becomes one of ARIA's memories only when
    MORICE accepts it — a model reading a document is not sufficient grounds
    for ARIA to believe something about his life.

    `quote` is required and verified to appear in the document. That check is
    what separates "extracted from your document" from "invented while looking
    at your document".
    """

    __tablename__ = "document_facts"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_id)
    document_id: Mapped[str] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), index=True
    )
    fact: Mapped[str] = mapped_column(Text)
    # personal | professional | financial | legal | project | other
    category: Mapped[str] = mapped_column(String(20), default="other", index=True)
    # Verbatim supporting text from the document.
    quote: Mapped[str] = mapped_column(String(400))
    # proposed | accepted | rejected
    status: Mapped[str] = mapped_column(String(20), default="proposed", index=True)
    memory_item_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    document: Mapped[Document] = relationship(back_populates="facts")


class Insight(Base):
    """Something ARIA noticed on her own and thinks MORICE should know.

    Persisted rather than computed on demand, for two reasons: "say it once"
    has to survive a restart, and a dismissal has to stay dismissed. A
    proactive assistant that re-raises everything it has ever noticed, every
    time it runs, is one you learn to ignore — and an ignored assistant is
    strictly worse than a silent one.

    `key` is stable for a given underlying situation, so re-running the checks
    updates an existing row instead of creating a duplicate.
    """

    __tablename__ = "insights"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_id)
    key: Mapped[str] = mapped_column(String(200), unique=True, index=True)
    severity: Mapped[str] = mapped_column(String(20), default="fyi", index=True)
    title: Mapped[str] = mapped_column(String(300))
    detail: Mapped[str] = mapped_column(Text, default="")
    link: Mapped[str] = mapped_column(String(200), default="")
    # What MORICE could do about it. An insight with no next step should not
    # have been raised.
    action: Mapped[str] = mapped_column(String(300), default="")
    # open | dismissed
    status: Mapped[str] = mapped_column(String(20), default="open", index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, index=True
    )
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now
    )
    dismissed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


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
