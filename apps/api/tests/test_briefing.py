"""Tests for the daily briefing.

The guarantees that matter, all of them about honesty rather than features:

  * nothing is invented — every item corresponds to a record
  * an empty period says so, and is distinguishable from a failure
  * a queued message is never reported as a sent one
  * failures appear, rather than being smoothed out of the summary
  * the window is respected: yesterday's news is not today's
"""

from datetime import timedelta

from fastapi.testclient import TestClient


def _sections(payload: dict) -> dict[str, dict]:
    return {s["key"]: s for s in payload["sections"]}


# ---------- nothing to report ----------

def test_a_quiet_period_says_so_plainly(client: TestClient) -> None:
    """"Nothing happened" is a real answer, and must not look like an error."""
    body = client.get("/briefing").json()
    assert body["quiet"] is True
    assert body["sections"] == []
    assert "Nothing happened" in body["headline"]


def test_the_window_is_reported_so_the_answer_is_checkable(
    client: TestClient,
) -> None:
    body = client.get("/briefing?hours=6").json()
    assert body["hours"] == 6
    from datetime import datetime

    since = datetime.fromisoformat(body["since"])
    until = datetime.fromisoformat(body["until"])
    assert abs((until - since) - timedelta(hours=6)) < timedelta(seconds=5)


# ---------- what happened ----------

def test_messages_that_arrived_are_counted_per_person(client: TestClient) -> None:
    for body in ("hey", "you around?"):
        client.post(
            "/whatsapp/simulate",
            json={"handle": "ann@s.whatsapp.net", "name": "Ann", "body": body},
        )
    client.post(
        "/whatsapp/simulate",
        json={"handle": "bob@s.whatsapp.net", "name": "Bob", "body": "hello"},
    )

    section = _sections(client.get("/briefing").json())["messages"]
    assert "3 messages" in section["summary"]
    assert "2 people" in section["summary"]
    titles = " ".join(i["title"] for i in section["items"])
    assert "Ann — 2 messages" in titles
    assert "Bob — 1 message" in titles


def test_a_queued_reply_is_not_reported_as_sent(
    client: TestClient, auth_enabled
) -> None:
    """The distinction the whole module exists for.

    ARIA can approve a reply and still not deliver it — no linked device, a
    dead sender, a closed socket. Reporting that as "handled" would be the
    single most misleading thing this briefing could say.
    """
    from tests.test_sending import _incoming, _ready_contact

    _ready_contact(client)
    _incoming(client, "hey")

    section = _sections(client.get("/briefing").json())["handled"]
    assert "queued" in section["summary"]
    assert "sent" not in section["summary"]
    assert section["needs_attention"] is True  # unreviewed
    assert "queued" in section["items"][0]["detail"]


def test_a_delivered_reply_is_reported_as_sent(
    client: TestClient, ingest_secret, auth_enabled
) -> None:
    from tests.test_sending import _incoming, _ready_contact

    _ready_contact(client)
    _incoming(client, "hey")
    claimed = client.post(
        "/whatsapp/outbound/claim",
        headers={"X-ARIA-Ingest-Secret": ingest_secret},
    ).json()["messages"]
    client.post(
        "/whatsapp/outbound/confirm",
        json={"id": claimed[0]["id"], "ok": True},
        headers={"X-ARIA-Ingest-Secret": ingest_secret},
    )

    section = _sections(client.get("/briefing").json())["handled"]
    assert "1 reply sent" in section["summary"]


def test_a_failed_delivery_appears_as_a_failure(
    client: TestClient, ingest_secret, auth_enabled
) -> None:
    from tests.test_sending import _incoming, _ready_contact

    _ready_contact(client)
    _incoming(client, "hey")
    claimed = client.post(
        "/whatsapp/outbound/claim",
        headers={"X-ARIA-Ingest-Secret": ingest_secret},
    ).json()["messages"]
    client.post(
        "/whatsapp/outbound/confirm",
        json={"id": claimed[0]["id"], "ok": False, "error": "socket closed"},
        headers={"X-ARIA-Ingest-Secret": ingest_secret},
    )

    sections = _sections(client.get("/briefing").json())
    assert "failures" in sections
    assert "socket closed" in sections["failures"]["items"][0]["detail"]
    assert sections["failures"]["needs_attention"] is True


def test_pending_approvals_are_what_aria_is_waiting_on(client: TestClient) -> None:
    client.post("/actions/demo", json={"message": "follow up with the recruiter"})

    section = _sections(client.get("/briefing").json())["approvals"]
    assert "1 action waiting" in section["summary"]
    assert "recruiter" in section["items"][0]["title"]


def test_overdue_tasks_are_flagged_even_from_outside_the_window(
    client: TestClient,
) -> None:
    """A deadline missed last week is still today's problem."""
    from src.core import clock

    long_past = (clock.now() - timedelta(days=9)).isoformat()
    client.post(
        "/tasks",
        json={"title": "File the tax return", "kind": "deadline", "due_at": long_past},
    )

    section = _sections(client.get("/briefing?hours=1").json())["tasks"]
    assert "already overdue" in section["summary"]
    assert "overdue" in section["items"][0]["detail"]


def test_activity_outside_the_window_is_not_reported(client: TestClient) -> None:
    """Otherwise "what did I miss?" answers with things he has already seen."""
    import asyncio

    from sqlalchemy import select

    from src.core import clock
    from src.models import WhatsAppMessage

    client.post(
        "/whatsapp/simulate",
        json={"handle": "ann@s.whatsapp.net", "name": "Ann", "body": "hey"},
    )

    async def _age_it() -> None:
        async with client.session_maker() as session:
            message = (await session.execute(select(WhatsAppMessage))).scalars().one()
            message.sent_at = clock.now() - timedelta(days=3)
            await session.commit()

    asyncio.run(_age_it())

    body = client.get("/briefing?hours=24").json()
    assert "messages" not in _sections(body)
    # And a wider window finds it again, which proves the filter rather than
    # the absence of data.
    assert "messages" in _sections(client.get("/briefing?hours=96").json())


def test_cost_is_labelled_as_an_estimate_and_counts_local_calls(
    client: TestClient,
) -> None:
    conversation = client.post("/conversations").json()
    client.post(
        f"/conversations/{conversation['id']}/messages",
        json={"content": "hello ARIA"},
    )

    section = _sections(client.get("/briefing").json())["cost"]
    assert "estimated" in section["summary"]
    assert "model call" in section["summary"]


def test_the_headline_leads_with_what_needs_attention(
    client: TestClient, auth_enabled
) -> None:
    client.post(
        "/whatsapp/simulate",
        json={"handle": "ann@s.whatsapp.net", "name": "Ann", "body": "hey"},
    )
    client.post("/actions/demo", json={"message": "follow up"})

    body = client.get("/briefing").json()
    # Messages arrived too, but an action waiting on him outranks a count.
    assert "waiting for approval" in body["headline"]


def test_an_absurd_window_is_refused_rather_than_clamped(client: TestClient) -> None:
    assert client.get("/briefing?hours=0").status_code == 422
    assert client.get("/briefing?hours=100000").status_code == 422


def test_a_reply_aria_sent_herself_is_not_also_waiting_for_review(
    client: TestClient, auth_enabled
) -> None:
    """It must appear once, as work done — never also as work to do.

    ARIA writes a draft on the way to deciding, so an autonomous reply used to
    leave a "pending" draft behind: the briefing showed the same message twice,
    once under what she handled and once under what she needed him to send.
    """
    from tests.test_sending import _incoming, _ready_contact

    _ready_contact(client)
    _incoming(client, "hey")

    sections = _sections(client.get("/briefing").json())
    assert "handled" in sections
    assert "drafts" not in sections

    assert client.get("/whatsapp/drafts").json() == []
    autonomous = client.get("/whatsapp/drafts?status=autonomous").json()
    assert len(autonomous) == 1  # still on the record, just not asking for him
