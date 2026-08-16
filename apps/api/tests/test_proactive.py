"""Proactive engine tests.

The hard part of a proactive assistant is not noticing things. It is staying
worth listening to. So these tests care as much about what ARIA stays QUIET
about as about what she raises:

  * she says each thing once
  * a dismissal is respected
  * a broken check does not silence the working ones
  * she never acts on what she notices
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from src.models import (
    ActionRequest,
    AutonomousResponse,
    Contact,
    InboundMessage,
    Insight,
    MessageDraft,
    Task,
)
from src.proactive import Severity, engine as engine_module


def _run(client: TestClient, coro_factory):
    async def _go():
        async with client.session_maker() as session:
            return await coro_factory(session)

    return asyncio.run(_go())


def _stage(client: TestClient, *rows):
    def _do(session):
        async def _go():
            for row in rows:
                session.add(row)
            await session.commit()

        return _go()

    _run(client, _do)


def _check(client: TestClient) -> list[dict]:
    client.post("/proactive/run")
    return client.get("/proactive").json()


def _now():
    return datetime.now(timezone.utc)


# ---------- noticing things worth noticing ----------

def test_a_dead_lettered_message_is_raised_as_urgent(client: TestClient) -> None:
    """The highest-value check: a real message ARIA received and never handled.

    Nobody notices this on their own — from the sender's side it just looks
    like MORICE did not reply.
    """
    _stage(
        client,
        InboundMessage(
            dedupe_key="dead.1",
            handle="grace@s.whatsapp.net",
            name="Grace",
            body="are we still on for Thursday?",
            status="dead",
            attempts=5,
            last_error="RuntimeError: model unavailable",
        ),
    )

    insights = _check(client)
    assert len(insights) == 1
    assert insights[0]["severity"] == Severity.URGENT.value
    assert "Grace" in insights[0]["title"]
    assert "Thursday" in insights[0]["detail"]
    assert insights[0]["action"]  # never raised without a next step


def test_a_stalled_queue_is_distinguished_from_a_busy_one(
    client: TestClient,
) -> None:
    """Depth means busy; age means stuck. Only age is worth interrupting for."""
    # Busy: lots pending, but all fresh.
    _stage(
        client,
        *[
            InboundMessage(
                dedupe_key=f"fresh.{i}", handle="x@s.whatsapp.net", body=f"m{i}"
            )
            for i in range(40)
        ],
    )
    assert _check(client) == []

    # Stuck: one message, waiting far too long.
    _stage(
        client,
        InboundMessage(
            dedupe_key="old.1",
            handle="x@s.whatsapp.net",
            body="hello?",
            received_at=_now() - timedelta(minutes=45),
        ),
    )
    insights = _check(client)
    assert any("stopped processing" in i["title"] for i in insights)


def test_unreviewed_autonomous_replies_are_surfaced(client: TestClient) -> None:
    """Closes the learning loop: silence teaches ARIA nothing, so she asks."""
    contact = Contact(name="John", handle="john@s.whatsapp.net")
    _stage(client, contact)
    _stage(
        client,
        *[
            AutonomousResponse(
                contact_id=contact.id,
                incoming="hey",
                response="hey, all good",
                decision="auto_send",
                send_status="sent",
                user_reaction="none",
                created_at=_now() - timedelta(days=2),
            )
            for _ in range(4)
        ],
    )

    insights = _check(client)
    assert any("unreviewed" in i["title"] for i in insights)


def test_one_or_two_unreviewed_replies_are_not_worth_mentioning(
    client: TestClient,
) -> None:
    """An assistant that mentions everything trains you to ignore it."""
    contact = Contact(name="John", handle="john@s.whatsapp.net")
    _stage(client, contact)
    _stage(
        client,
        AutonomousResponse(
            contact_id=contact.id,
            incoming="hey",
            response="hey",
            decision="auto_send",
            send_status="sent",
            created_at=_now() - timedelta(days=2),
        ),
    )
    assert _check(client) == []


def test_overdue_tasks_are_grouped_into_one_insight(client: TestClient) -> None:
    """Five notifications about five tasks is how a list becomes noise."""
    _stage(
        client,
        *[
            Task(
                title=f"task {i}",
                status="open",
                due_at=_now() - timedelta(days=1),
            )
            for i in range(5)
        ],
    )
    insights = _check(client)
    overdue = [i for i in insights if "overdue" in i["title"]]
    assert len(overdue) == 1
    assert "5 task(s)" in overdue[0]["title"]


def test_stale_drafts_are_flagged_as_probably_useless(client: TestClient) -> None:
    contact = Contact(name="Ann", handle="ann@s.whatsapp.net")
    _stage(client, contact)
    _stage(
        client,
        MessageDraft(
            contact_id=contact.id,
            incoming="you free tomorrow?",
            draft="yeah",
            status="pending",
            created_at=_now() - timedelta(days=4),
        ),
    )
    insights = _check(client)
    assert any("2+ days old" in i["title"] for i in insights)


def test_long_waiting_approvals_are_raised(client: TestClient) -> None:
    _stage(
        client,
        ActionRequest(
            agent="communication",
            action_type="email.send",
            summary="Reply to recruiter",
            payload={},
            status="pending",
            created_at=_now() - timedelta(hours=8),
        ),
    )
    insights = _check(client)
    assert any("waiting over 6 hours" in i["title"] for i in insights)


def test_withdrawn_autonomy_is_explained_rather_than_silent(
    client: TestClient,
) -> None:
    """An automatic downgrade MORICE never hears about looks like ARIA
    mysteriously going quiet."""
    contact = Contact(
        name="John",
        handle="john@s.whatsapp.net",
        trust_level="high",
        autonomy_enabled=True,
    )
    _stage(client, contact)
    _stage(
        client,
        *[
            AutonomousResponse(
                contact_id=contact.id,
                incoming="hey",
                response="hey",
                decision="auto_send",
                send_status="sent",
                user_reaction="corrected",
                correction="not like that",
            )
            for _ in range(5)
        ],
    )

    insights = _check(client)
    assert any("stopped auto-replying" in i["title"] for i in insights)


# ---------- staying worth listening to ----------

def test_the_same_situation_is_only_raised_once(client: TestClient) -> None:
    """Nagging is how a notification channel dies."""
    _stage(
        client,
        InboundMessage(
            dedupe_key="dead.1",
            handle="x@s.whatsapp.net",
            body="hello",
            status="dead",
            attempts=5,
            last_error="boom",
        ),
    )

    first = client.post("/proactive/run").json()
    assert first["new_insights"] == 1

    for _ in range(3):
        assert client.post("/proactive/run").json()["new_insights"] == 0

    assert len(client.get("/proactive").json()) == 1


def test_a_dismissed_insight_stays_dismissed(client: TestClient) -> None:
    _stage(
        client,
        InboundMessage(
            dedupe_key="dead.1",
            handle="x@s.whatsapp.net",
            body="hello",
            status="dead",
            attempts=5,
            last_error="boom",
        ),
    )
    insight = _check(client)[0]

    client.post(f"/proactive/{insight['id']}/dismiss")
    assert client.get("/proactive").json() == []

    # Re-running does not resurrect it during the cooldown.
    client.post("/proactive/run")
    assert client.get("/proactive").json() == []


def test_a_dismissed_problem_returns_after_the_cooldown(
    client: TestClient,
) -> None:
    """A problem dismissed but never fixed should come back.

    Otherwise ARIA helps MORICE forget about it, which is the opposite of the
    point.
    """
    _stage(
        client,
        InboundMessage(
            dedupe_key="dead.1",
            handle="x@s.whatsapp.net",
            body="hello",
            status="dead",
            attempts=5,
            last_error="boom",
        ),
    )
    insight = _check(client)[0]
    client.post(f"/proactive/{insight['id']}/dismiss")

    def _age_the_dismissal(session):
        async def _go():
            row = (
                await session.execute(select(Insight).where(Insight.key == insight["key"]))
            ).scalar_one()
            row.dismissed_at = _now() - timedelta(days=3)
            await session.commit()

        return _go()

    _run(client, _age_the_dismissal)

    client.post("/proactive/run")
    assert len(client.get("/proactive").json()) == 1


def test_urgent_insights_sort_above_older_trivia(client: TestClient) -> None:
    _stage(
        client,
        Task(title="old thing", status="open", due_at=_now() - timedelta(days=9)),
        InboundMessage(
            dedupe_key="dead.1",
            handle="x@s.whatsapp.net",
            body="hello",
            status="dead",
            attempts=5,
            last_error="boom",
        ),
    )
    insights = _check(client)
    assert insights[0]["severity"] == "urgent"


def test_a_broken_check_does_not_silence_the_others(
    client: TestClient, monkeypatch
) -> None:
    """The check most likely to fail is the one watching what is broken."""

    async def explode(session):
        raise RuntimeError("this check is broken")

    monkeypatch.setitem(engine_module._checks, "stuck_messages", explode)

    _stage(
        client,
        Task(title="overdue thing", status="open", due_at=_now() - timedelta(days=1)),
    )
    insights = _check(client)
    assert any("overdue" in i["title"] for i in insights)


def test_a_quiet_healthy_system_produces_nothing(client: TestClient) -> None:
    """Silence is the correct output when there is nothing to say."""
    assert _check(client) == []


# ---------- it notices, it does not act ----------

def test_the_proactive_engine_never_sends_or_queues_anything(
    client: TestClient,
) -> None:
    """It observes and reports. Acting is MORICE's decision, routed through
    the normal autonomy layer."""
    contact = Contact(
        name="John", handle="john@s.whatsapp.net", trust_level="high",
        autonomy_enabled=True,
    )
    _stage(client, contact)
    _stage(
        client,
        InboundMessage(
            dedupe_key="dead.1",
            handle="john@s.whatsapp.net",
            body="are you there?",
            status="dead",
            attempts=5,
            last_error="boom",
        ),
        MessageDraft(
            contact_id=contact.id,
            incoming="you free?",
            draft="yeah",
            status="pending",
            created_at=_now() - timedelta(days=4),
        ),
    )

    client.post("/proactive/run")

    assert client.get("/whatsapp/outbound").json() == []
    assert client.get("/whatsapp/autonomous").json() == []
    # And no gateway actions were created either.
    requests = _run(client, lambda s: s.execute(select(ActionRequest)))
    assert list(requests.scalars()) == []


# ---------- the scheduler ----------

def test_scheduler_status_is_visible(client: TestClient) -> None:
    """A loop nobody can see the state of stops working unnoticed."""
    status = client.get("/proactive/status").json()
    assert "running" in status and "last_error" in status


@pytest.mark.asyncio
async def test_scheduler_survives_a_failing_run() -> None:
    """The moment something breaks is when the checks matter most."""
    from src.proactive.scheduler import Scheduler

    calls = {"n": 0}

    async def flaky():
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("first run explodes")

    scheduler = Scheduler(flaky, interval_seconds=0.01, name="test")
    scheduler.start()
    await asyncio.sleep(0.1)
    await scheduler.stop()

    assert calls["n"] >= 2, "the loop did not survive the first failure"
    assert scheduler.runs >= 2


# ---------- career and learning ----------

def test_an_imminent_interview_is_raised(client: TestClient) -> None:
    """The one career event worth interrupting for: preparation has to happen
    before it, not after."""
    _stage(
        client,
        Task(
            title="Interview with Acme",
            kind="interview",
            status="open",
            due_at=_now() + timedelta(hours=20),
        ),
    )
    insights = _check(client)
    assert any("Interview in" in i["title"] for i in insights)


def test_a_distant_interview_is_not_raised_yet(client: TestClient) -> None:
    """Reminding someone about next month's interview today is noise."""
    _stage(
        client,
        Task(
            title="Interview with Acme",
            kind="interview",
            status="open",
            due_at=_now() + timedelta(days=10),
        ),
    )
    assert not any("Interview in" in i["title"] for i in _check(client))


def test_stale_applications_are_grouped(client: TestClient) -> None:
    from src.models import JobApplication

    _stage(
        client,
        *[
            JobApplication(
                company=f"Company {i}",
                role="Backend Developer",
                status="applied",
                created_at=_now() - timedelta(days=40),
            )
            for i in range(4)
        ],
    )
    stale = [i for i in _check(client) if "no update in 3 weeks" in i["title"]]
    assert len(stale) == 1
    assert "4 application(s)" in stale[0]["title"]


def test_neglected_learning_is_mentioned_gently(client: TestClient) -> None:
    """An assistant that nags about self-improvement is one you mute."""
    from src.models import LearningTopic

    _stage(
        client,
        LearningTopic(
            name="Rust", status="learning", created_at=_now() - timedelta(days=60)
        ),
    )
    topics = [i for i in _check(client) if "topic(s)" in i["title"]]
    assert len(topics) == 1
    assert topics[0]["severity"] == Severity.FYI.value
