"""Durable inbound queue — the reason a WhatsApp message cannot be lost.

The failure mode this replaces: the bridge received a message, ARIA's API was
down, the POST failed, and the message was gone forever. There was no record
that it had ever existed.

The fix has two halves, and both are needed:

  * **Bridge side** (`apps/wa-bridge/spool.js`) — every message is written to
    disk before the network is touched, and only deleted once ARIA has
    acknowledged it. That covers ARIA being *unreachable*.

  * **This module** — ingest persists the message and commits before any
    processing is attempted. That covers ARIA being *reachable but failing*:
    a crash, a model outage, a bug in the classifier. The row survives, and
    the worker tries again.

Processing is deliberately separated from receiving. Receiving must be fast
and near-infallible (one INSERT); understanding is slow and fails in a dozen
ways. Coupling them is what made the original design lose data.

Retries use exponential backoff stored as a timestamp rather than an in-memory
sleep, so backoff survives a restart. After `MAX_ATTEMPTS` a message is parked
in `dead` state — visible, retryable by hand, never silently discarded.
"""

from __future__ import annotations

import asyncio
import logging
import random
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from src.models import InboundMessage

logger = logging.getLogger(__name__)

# After this many failed attempts a message stops retrying and waits for a
# human. Five attempts with the backoff below spans roughly 15 minutes, which
# comfortably outlasts an API restart or a model reload.
MAX_ATTEMPTS = 5

# Backoff: 10s, 20s, 40s, 80s, 160s (plus jitter), capped.
_BACKOFF_BASE_SECONDS = 10
_BACKOFF_CAP_SECONDS = 300

# A row claimed by a worker that then died would sit in `processing` forever.
# After this long, any worker may reclaim it. Set well above the slowest
# realistic processing time (a cloud model call plus a draft).
STALE_CLAIM_SECONDS = 300


def _now() -> datetime:
    return datetime.now(timezone.utc)


def backoff_delay(attempts: int) -> timedelta:
    """Delay before the next attempt. Jittered so retries never synchronise.

    Jitter matters when the API comes back up and a whole spool drains at
    once: without it, every message would retry in the same instant and
    re-overload whatever just recovered.
    """
    raw = _BACKOFF_BASE_SECONDS * (2 ** max(attempts - 1, 0))
    capped = min(raw, _BACKOFF_CAP_SECONDS)
    return timedelta(seconds=capped * (0.75 + random.random() * 0.5))


async def enqueue(
    session: AsyncSession,
    *,
    dedupe_key: str,
    handle: str,
    name: str = "",
    body: str,
    direction: str = "in",
    channel: str = "whatsapp",
    simulated: bool = False,
    sent_at: datetime | None = None,
) -> tuple[InboundMessage, bool]:
    """Durably record one received message.

    Returns `(row, created)`. `created is False` means this was a duplicate
    redelivery, and the caller must treat it as a success — the bridge needs a
    positive acknowledgement so it can drop the message from its spool, or it
    will redeliver forever.

    Duplicate detection is the database's UNIQUE constraint, not a prior SELECT.
    A check-then-insert would race two concurrent deliveries of the same
    message through the gap and process it twice.
    """
    row = InboundMessage(
        dedupe_key=dedupe_key,
        handle=handle,
        name=name,
        body=body,
        direction=direction,
        channel=channel,
        simulated=simulated,
        sent_at=sent_at,
        next_attempt_at=_now(),
    )
    session.add(row)
    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        existing = (
            await session.execute(
                select(InboundMessage).where(InboundMessage.dedupe_key == dedupe_key)
            )
        ).scalar_one()
        logger.info(
            "Duplicate message %s ignored (already %s)", dedupe_key, existing.status
        )
        return existing, False

    return row, True


async def claim_next(session: AsyncSession) -> InboundMessage | None:
    """Claim one message that is due for processing, or None.

    Also reclaims rows abandoned in `processing` by a worker that died — the
    exact situation an API crash creates, and the one a naive queue leaks.
    """
    now = _now()
    stale_before = now - timedelta(seconds=STALE_CLAIM_SECONDS)

    query = (
        select(InboundMessage)
        .where(
            (
                (InboundMessage.status == "pending")
                & (InboundMessage.next_attempt_at <= now)
            )
            | (
                (InboundMessage.status == "processing")
                & (InboundMessage.claimed_at < stale_before)
            )
        )
        .order_by(InboundMessage.received_at)
        .limit(1)
    )
    # Row-level locking so two workers can never claim the same message.
    # SQLite (tests only) has no SELECT ... FOR UPDATE and is single-writer
    # anyway, so the lock is simply omitted there rather than emulated.
    if session.bind is not None and session.bind.dialect.name == "postgresql":
        query = query.with_for_update(skip_locked=True)

    row = (await session.execute(query)).scalar_one_or_none()

    if row is None:
        return None

    if row.status == "processing":
        logger.warning(
            "Reclaiming message %s abandoned mid-processing (attempt %d)",
            row.dedupe_key,
            row.attempts,
        )
    row.status = "processing"
    row.claimed_at = now
    await session.commit()
    return row


async def mark_done(
    session: AsyncSession, row: InboundMessage, outcome: str = ""
) -> None:
    row.status = "done"
    row.processed_at = _now()
    row.last_error = ""
    row.outcome = outcome[:300]
    await session.commit()


async def mark_failed(
    session: AsyncSession, row: InboundMessage, error: str
) -> None:
    """Record a failed attempt: schedule a retry, or park it as dead.

    A dead message is not a lost message. It stays in the table, appears in the
    dashboard's error list, and can be retried by hand once the cause is fixed.
    """
    row.attempts += 1
    row.last_error = error[:2000]
    row.claimed_at = None

    if row.attempts >= MAX_ATTEMPTS:
        row.status = "dead"
        row.processed_at = _now()
        logger.error(
            "Message %s dead after %d attempts: %s",
            row.dedupe_key,
            row.attempts,
            error,
        )
    else:
        row.status = "pending"
        row.next_attempt_at = _now() + backoff_delay(row.attempts)
        logger.warning(
            "Message %s failed (attempt %d/%d), retrying at %s: %s",
            row.dedupe_key,
            row.attempts,
            MAX_ATTEMPTS,
            row.next_attempt_at.isoformat(),
            error,
        )
    await session.commit()


async def revive(session: AsyncSession, message_id: str) -> InboundMessage | None:
    """Put a dead message back in the queue, attempts reset.

    The manual half of the recovery story: MORICE fixes whatever broke, then
    replays the messages that broke on it.
    """
    row = await session.get(InboundMessage, message_id)
    if row is None:
        return None
    row.status = "pending"
    row.attempts = 0
    row.next_attempt_at = _now()
    row.claimed_at = None
    row.last_error = ""
    await session.commit()
    return row


async def stats(session: AsyncSession) -> dict:
    """Queue health, for the dashboard and for tests.

    Processing state must be observable; a queue you cannot see is a queue you
    cannot trust.
    """
    rows = await session.execute(
        select(InboundMessage.status, func.count(InboundMessage.id)).group_by(
            InboundMessage.status
        )
    )
    counts = {status: count for status, count in rows.all()}

    oldest = (
        await session.execute(
            select(func.min(InboundMessage.received_at)).where(
                InboundMessage.status.in_(("pending", "processing"))
            )
        )
    ).scalar_one_or_none()

    # SQLite (tests) drops the timezone on the way back out, so an aggregate
    # can return a naive datetime where Postgres returns an aware one.
    # Subtracting the two kinds raises, so normalise before doing arithmetic.
    if oldest is not None and oldest.tzinfo is None:
        oldest = oldest.replace(tzinfo=timezone.utc)

    return {
        "received": sum(counts.values()),
        "pending": counts.get("pending", 0),
        "processing": counts.get("processing", 0),
        "done": counts.get("done", 0),
        "dead": counts.get("dead", 0),
        "oldest_unprocessed_at": oldest,
        "backlog_seconds": (
            round((_now() - oldest).total_seconds()) if oldest is not None else 0
        ),
    }


async def list_messages(
    session: AsyncSession, *, status: str | None = None, limit: int = 50
) -> list[InboundMessage]:
    query = select(InboundMessage).order_by(InboundMessage.received_at.desc())
    if status:
        query = query.where(InboundMessage.status == status)
    return list((await session.execute(query.limit(limit))).scalars())


class QueueWorker:
    """Background drain loop.

    Deliberately single-threaded and slow-polling. Message volume for one
    person is tiny; the scarce resource is the local model, not the loop. One
    message at a time also means a poison message cannot starve the others —
    it fails, backs off, and the next one runs.
    """

    def __init__(self, session_factory, process, *, poll_seconds: float = 2.0):
        self._session_factory = session_factory
        self._process = process
        self._poll_seconds = poll_seconds
        self._task: asyncio.Task | None = None
        self._stopping = asyncio.Event()

    def start(self) -> None:
        if self._task is None or self._task.done():
            self._stopping.clear()
            self._task = asyncio.create_task(self._run(), name="whatsapp-queue-worker")
            logger.info("WhatsApp queue worker started")

    async def stop(self) -> None:
        self._stopping.set()
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass
            self._task = None
            logger.info("WhatsApp queue worker stopped")

    async def drain_once(self) -> int:
        """Process everything currently due. Returns how many were handled.

        Exposed separately from the loop so tests can drive the queue
        deterministically instead of sleeping and hoping.
        """
        handled = 0
        while True:
            async with self._session_factory() as session:
                row = await claim_next(session)
                if row is None:
                    return handled
                try:
                    outcome = await self._process(session, row)
                    await mark_done(session, row, outcome or "")
                except Exception as exc:  # noqa: BLE001 — every failure is retryable
                    await session.rollback()
                    await mark_failed(session, row, f"{type(exc).__name__}: {exc}")
            handled += 1

    async def _run(self) -> None:
        while not self._stopping.is_set():
            try:
                await self.drain_once()
            except Exception:  # noqa: BLE001 — the loop must outlive any error
                logger.exception("Queue worker iteration failed")
            try:
                await asyncio.wait_for(
                    self._stopping.wait(), timeout=self._poll_seconds
                )
            except TimeoutError:
                continue
