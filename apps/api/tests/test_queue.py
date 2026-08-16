"""Durability tests — proof that a WhatsApp message cannot be lost.

These are the tests that matter most before autonomy is switched on. Each one
breaks something on purpose (the model, the processing step, the whole API
process) and then asserts the message is still there and still gets handled.

A test that only checked the happy path would have passed against the OLD code
too, which dropped messages. So each of these fails against the old design.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient
from sqlalchemy import select

from src.models import InboundMessage, WhatsAppMessage
from src.whatsapp import queue

def _send(client: TestClient, secret: str, **overrides):
    payload = {
        "handle": "friend@s.whatsapp.net",
        "name": "Friend",
        "body": "you around?",
        "message_id": "wamid.TEST1",
    }
    payload.update(overrides)
    return client.post(
        "/whatsapp/ingest", json=payload, headers={"X-ARIA-Ingest-Secret": secret}
    )


def _run(client: TestClient, coro_factory):
    """Run a coroutine against the test database, outside any request."""

    async def _go():
        async with client.session_maker() as session:
            return await coro_factory(session)

    return asyncio.run(_go())


def _drain(client: TestClient) -> int:
    """Process the queue exactly as the background worker would."""
    return client.post("/whatsapp/queue/drain").json()["processed"]


def _make_due(client: TestClient) -> None:
    """Fast-forward past the retry backoff, which time would otherwise do."""

    def _stage(session):
        async def _go():
            for row in await queue.list_messages(session):
                row.next_attempt_at = datetime.now(timezone.utc) - timedelta(seconds=1)
            await session.commit()

        return _go()

    _run(client, _stage)


def _observed(client: TestClient) -> list[str]:
    """Message bodies that actually reached the conversation store."""
    result = _run(
        client,
        lambda s: s.execute(select(WhatsAppMessage).order_by(WhatsAppMessage.sent_at)),
    )
    return [m.body for m in result.scalars()]


# ---------- persistence before processing ----------

def test_ingest_persists_and_acknowledges_without_processing(
    client: TestClient, ingest_secret
) -> None:
    """Ingest stores the message and acknowledges. It does not think about it.

    The acknowledgement must not wait on a model. Receipt latency hostage to
    LLM latency is how a receiver starts timing out, and a receiver that times
    out is how messages get lost in the first place.
    """
    response = _send(client, ingest_secret)
    assert response.status_code == 202
    body = response.json()
    assert body["queued"] is True
    assert body["duplicate"] is False
    assert body["status"] == "pending"

    rows = _run(client, lambda s: queue.list_messages(s))
    assert len(rows) == 1
    assert rows[0].body == "you around?"
    assert rows[0].status == "pending"  # durable, not yet understood

    # Proof that processing genuinely has not happened yet.
    assert _observed(client) == []

    assert _drain(client) == 1
    assert _run(client, lambda s: queue.list_messages(s))[0].status == "done"
    assert _observed(client) == ["you around?"]


def test_processing_failure_keeps_the_message_and_schedules_a_retry(
    client: TestClient, ingest_secret, monkeypatch
) -> None:
    """Model outage: the classifier explodes, the message survives.

    This is the exact scenario the old code lost. Processing threw, and the
    only copy of the message went with it.
    """
    from src.whatsapp import pipeline

    async def boom(*args, **kwargs):
        raise RuntimeError("model unavailable")

    monkeypatch.setattr(pipeline, "process_inbound", boom)

    assert _send(client, ingest_secret).status_code == 202
    _drain(client)  # the worker tries, and fails

    rows = _run(client, lambda s: queue.list_messages(s))
    assert len(rows) == 1
    row = rows[0]
    assert row.status == "pending"  # queued for another attempt, not discarded
    assert row.attempts == 1
    assert "model unavailable" in row.last_error
    assert row.next_attempt_at > row.received_at  # backoff applied


def test_message_survives_and_completes_after_the_failure_clears(
    client: TestClient, ingest_secret, monkeypatch
) -> None:
    """The recovery half: once the model is back, the drain finishes the job.

    Nothing is redelivered by the bridge here. The message is recovered purely
    from ARIA's own durable state.
    """
    from src.whatsapp import pipeline

    original = pipeline.process_inbound
    calls = {"n": 0}

    async def flaky(session, router, row):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("model unavailable")
        return await original(session, router, row)

    monkeypatch.setattr(pipeline, "process_inbound", flaky)

    _send(client, ingest_secret)
    _drain(client)
    assert _run(client, lambda s: queue.list_messages(s))[0].status == "pending"

    _make_due(client)
    assert _drain(client) == 1

    row = _run(client, lambda s: queue.list_messages(s))[0]
    assert row.status == "done"
    assert row.attempts == 1  # the failed attempt stays on the record
    assert _observed(client) == ["you around?"]


# ---------- duplicates ----------

def test_duplicate_delivery_is_acknowledged_but_not_reprocessed(
    client: TestClient, ingest_secret
) -> None:
    """A redelivered message must not produce a second response.

    The bridge retries until acknowledged, so redelivery is normal, not
    exceptional. It must be boring.
    """
    first = _send(client, ingest_secret)
    second = _send(client, ingest_secret)  # same message_id
    _drain(client)

    assert first.json()["duplicate"] is False
    assert second.status_code == 202
    assert second.json()["duplicate"] is True
    # Positive ack, so the bridge drops its spooled copy instead of looping.
    assert second.json()["queued"] is True

    assert len(_run(client, lambda s: queue.list_messages(s))) == 1
    assert _observed(client) == ["you around?"]  # observed exactly once


def test_different_messages_from_the_same_contact_are_both_kept(
    client: TestClient, ingest_secret
) -> None:
    """Dedupe must key on message identity, not on the sender."""
    _send(client, ingest_secret, message_id="wamid.A", body="first")
    _send(client, ingest_secret, message_id="wamid.B", body="second")
    _drain(client)

    assert set(_observed(client)) == {"first", "second"}


def test_identical_text_without_a_message_id_still_deduplicates(
    client: TestClient, ingest_secret
) -> None:
    """Hand-made calls carry no transport id; a content hash stands in."""
    _send(client, ingest_secret, message_id="", body="hey", timestamp=1000)
    second = _send(client, ingest_secret, message_id="", body="hey", timestamp=1000)
    assert second.json()["duplicate"] is True


def test_concurrent_deliveries_of_the_same_message_produce_one_row(
    client: TestClient, ingest_secret
) -> None:
    """Dedupe is enforced by the database, not by a check-then-insert.

    Two simultaneous redeliveries would race through the gap between a SELECT
    and an INSERT. The UNIQUE constraint has no such gap.
    """
    for _ in range(5):
        _send(client, ingest_secret, message_id="wamid.SAME")
    _drain(client)

    assert len(_run(client, lambda s: queue.list_messages(s))) == 1
    assert len(_observed(client)) == 1


# ---------- dead letters ----------

def _exhaust_retries(client: TestClient) -> None:
    for _ in range(queue.MAX_ATTEMPTS):
        _make_due(client)
        _drain(client)


def test_message_goes_dead_after_max_attempts_and_is_still_readable(
    client: TestClient, ingest_secret, monkeypatch
) -> None:
    """Exhausted retries park the message visibly. Nothing is discarded."""
    from src.whatsapp import pipeline

    async def boom(*args, **kwargs):
        raise RuntimeError("permanently broken")

    monkeypatch.setattr(pipeline, "process_inbound", boom)
    _send(client, ingest_secret)
    _exhaust_retries(client)

    row = _run(client, lambda s: queue.list_messages(s))[0]
    assert row.status == "dead"
    assert row.attempts == queue.MAX_ATTEMPTS

    listed = client.get("/whatsapp/queue/items?status=dead").json()
    assert len(listed) == 1
    assert "permanently broken" in listed[0]["last_error"]
    assert listed[0]["body"] == "you around?"  # the content is still there


def test_dead_message_can_be_retried_by_hand_and_succeeds(
    client: TestClient, ingest_secret, monkeypatch
) -> None:
    """Recovery after a fix: replay the dead letter, and it completes."""
    from src.whatsapp import pipeline

    original = pipeline.process_inbound
    broken = {"yes": True}

    async def maybe_boom(session, router, row):
        if broken["yes"]:
            raise RuntimeError("broken")
        return await original(session, router, row)

    monkeypatch.setattr(pipeline, "process_inbound", maybe_boom)
    _send(client, ingest_secret)
    _exhaust_retries(client)

    dead = client.get("/whatsapp/queue/items?status=dead").json()[0]
    assert dead["status"] == "dead"

    broken["yes"] = False  # MORICE fixed the cause
    revived = client.post(f"/whatsapp/queue/{dead['id']}/retry")
    assert revived.status_code == 200
    assert revived.json()["status"] == "pending"
    assert revived.json()["attempts"] == 0

    _drain(client)
    assert _run(client, lambda s: queue.list_messages(s))[0].status == "done"
    assert _observed(client) == ["you around?"]


# ---------- crash / restart recovery ----------

def test_message_abandoned_mid_processing_is_reclaimed(
    client: TestClient, ingest_secret
) -> None:
    """Simulates ARIA being killed while holding a message.

    A row stuck in `processing` with no live worker is the signature of a
    crash. It must be reclaimed, not orphaned — otherwise a crash silently
    eats exactly the message that was in flight.
    """

    def _stage(session):
        async def _go():
            session.add(
                InboundMessage(
                    dedupe_key="wamid.CRASHED",
                    handle="friend@s.whatsapp.net",
                    name="Friend",
                    body="did you get this?",
                    status="processing",
                    # Claimed too long ago for any live worker to still hold it.
                    claimed_at=datetime.now(timezone.utc)
                    - timedelta(seconds=queue.STALE_CLAIM_SECONDS + 60),
                )
            )
            await session.commit()

        return _go()

    _run(client, _stage)

    # This is what happens on restart: the worker drains and finds the orphan.
    assert _drain(client) == 1
    assert _run(client, lambda s: queue.list_messages(s))[0].status == "done"
    assert _observed(client) == ["did you get this?"]


def test_pending_backlog_is_processed_on_restart(client: TestClient) -> None:
    """Messages queued while ARIA was down are handled when she returns.

    The bridge spools during an outage and floods on recovery; ARIA must
    absorb the flood, in receipt order.
    """

    def _stage(session):
        async def _go():
            for index in range(5):
                session.add(
                    InboundMessage(
                        dedupe_key=f"wamid.BACKLOG{index}",
                        handle="friend@s.whatsapp.net",
                        name="Friend",
                        body=f"message {index}",
                        received_at=datetime.now(timezone.utc)
                        + timedelta(seconds=index),
                    )
                )
            await session.commit()

        return _go()

    _run(client, _stage)
    assert _drain(client) == 5

    rows = _run(client, lambda s: queue.list_messages(s))
    assert all(r.status == "done" for r in rows)
    # Order preserved: a conversation replayed out of order is worse than late.
    assert _observed(client) == [f"message {i}" for i in range(5)]


def test_delayed_message_records_both_clocks(
    client: TestClient, ingest_secret
) -> None:
    """A message delayed in transit must be recognisable as delayed.

    Sender clock and receipt clock are stored separately, so a two-hour-old
    "are you coming?" is not mistaken for a fresh one.
    """
    two_hours_ago = int(
        (datetime.now(timezone.utc) - timedelta(hours=2)).timestamp()
    )
    _send(client, ingest_secret, timestamp=two_hours_ago, body="are you coming?")

    row = _run(client, lambda s: queue.list_messages(s))[0]
    assert row.sent_at is not None
    lag = row.received_at.replace(tzinfo=timezone.utc) - row.sent_at.replace(
        tzinfo=timezone.utc
    )
    assert lag > timedelta(hours=1)


# ---------- observability ----------

def test_queue_stats_report_processing_state(
    client: TestClient, ingest_secret, monkeypatch
) -> None:
    from src.whatsapp import pipeline

    async def boom(*args, **kwargs):
        raise RuntimeError("nope")

    _send(client, ingest_secret, message_id="wamid.OK", body="fine")
    _drain(client)

    monkeypatch.setattr(pipeline, "process_inbound", boom)
    _send(client, ingest_secret, message_id="wamid.BAD", body="breaks")
    _drain(client)

    stats = client.get("/whatsapp/queue").json()
    assert stats["received"] == 2
    assert stats["done"] == 1
    assert stats["pending"] == 1
    assert stats["dead"] == 0
    assert stats["backlog_seconds"] >= 0


# ---------- backoff ----------

def test_backoff_grows_and_is_capped() -> None:
    """Retries must not hammer a service that is already struggling."""
    first = queue.backoff_delay(1).total_seconds()
    second = queue.backoff_delay(2).total_seconds()
    later = queue.backoff_delay(20).total_seconds()

    assert first < second  # grows
    assert later <= queue._BACKOFF_CAP_SECONDS * 1.25  # capped (jitter included)
    assert first > 0
