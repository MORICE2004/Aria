"""Send-path tests — what stands between a decision and a sent message.

The directive's rule for this area: *do not simply remove the approval check.*
These tests exist to prove it was not removed. Autonomous sending is a
pre-authorisation of the same gateway, not a bypass of it, and the gate is
re-checked at execution time and again at handover.

The scenario driving most of them: MORICE presses stop AFTER ARIA decided to
reply but BEFORE the message physically leaves. Every layer must catch it,
because that gap is where a kill switch either works or is theatre.
"""

from __future__ import annotations

import asyncio

from fastapi.testclient import TestClient
from sqlalchemy import select

from src.models import ActionRequest, AuditEvent, AutonomousResponse, StylePattern


def _run(client: TestClient, coro_factory):
    async def _go():
        async with client.session_maker() as session:
            return await coro_factory(session)

    return asyncio.run(_go())


def _teach_aria_to_write(client: TestClient) -> None:
    """Give ARIA a confident style profile.

    Autonomy requires communication confidence above 0.70, which normally
    takes ~19 observed messages. Seeding the measured patterns directly keeps
    these tests about the SEND PATH rather than about the learning curve.
    """

    def _stage(session):
        async def _go():
            for dimension, value in (
                ("avg_words", "5.4"),
                ("greeting", "hey"),
                ("register", "lowercase, casual"),
                ("emoji_rate", "0.1"),
            ):
                session.add(
                    StylePattern(
                        dimension=dimension,
                        scope="global",
                        value=value,
                        confidence=0.9,
                        evidence_count=40,
                        source="observed",
                    )
                )
            await session.commit()

        return _go()

    _run(client, _stage)


def _ready_contact(client: TestClient, handle="john@s.whatsapp.net") -> str:
    """A contact cleared for autonomy, in a system cleared for autonomy."""
    _teach_aria_to_write(client)
    contact = client.post(
        "/whatsapp/contacts",
        json={"name": "John", "handle": handle, "relationship": "friend"},
    ).json()
    client.patch(f"/whatsapp/contacts/{contact['id']}", json={"trust_level": "high"})
    client.patch(
        f"/whatsapp/contacts/{contact['id']}",
        json={
            "autonomy_enabled": True,
            "allowed_actions": ["greeting", "routine_reply", "status_update"],
        },
    )
    client.patch("/whatsapp/autonomy", json={"mode": "limited_autonomy"})
    return contact["id"]


def _incoming(client: TestClient, body="hey, you around?", handle="john@s.whatsapp.net"):
    return client.post(
        "/whatsapp/simulate", json={"handle": handle, "name": "John", "body": body}
    ).json()


# ---------- the happy path, and what it records ----------

def test_a_permitted_low_risk_message_is_sent_autonomously(
    client: TestClient,
) -> None:
    _ready_contact(client)
    _incoming(client, "hey")

    responses = client.get("/whatsapp/autonomous").json()
    assert len(responses) == 1
    response = responses[0]
    assert response["decision"] == "auto_send"
    assert response["risk_level"] == "low"
    assert response["action_type"] == "greeting"
    assert response["communication_confidence"] >= 0.7
    assert response["reasons"] if "reasons" in response else response["decision_reasons"]

    outbound = client.get("/whatsapp/outbound").json()
    assert len(outbound) == 1
    assert outbound[0]["status"] == "pending"
    assert outbound[0]["origin"] == "autonomous"


def test_an_autonomous_send_still_goes_through_the_action_gateway(
    client: TestClient,
) -> None:
    """The approval check was not removed — it was pre-authorised.

    There is still an ActionRequest, still an executor, still an audit trail.
    """
    _ready_contact(client)
    _incoming(client, "hey")

    requests = _run(
        client,
        lambda s: s.execute(
            select(ActionRequest).where(ActionRequest.action_type == "whatsapp.send")
        ),
    )
    request = list(requests.scalars())[0]
    assert request.status == "executed"
    assert request.agent == "whatsapp"

    events = _run(
        client,
        lambda s: s.execute(
            select(AuditEvent).where(AuditEvent.action_request_id == request.id)
        ),
    )
    names = [e.event for e in events.scalars()]
    assert "submitted" in names
    assert "approved" in names
    assert "executed" in names
    # And it is explicitly marked as policy-approved, not clicked.
    assert "pre_authorised" in names


def test_the_decision_and_its_reasons_are_recorded_for_later_scrutiny(
    client: TestClient,
) -> None:
    _ready_contact(client)
    _incoming(client, "hey")

    response = client.get("/whatsapp/autonomous").json()[0]
    assert response["decision_reasons"], "an autonomous send must explain itself"
    assert response["autonomy_mode"] == "limited_autonomy"
    assert response["model"]


# ---------- the kill switch ----------

def test_emergency_stop_cancels_messages_already_queued(client: TestClient) -> None:
    """The gap between deciding and sending is where a kill switch matters."""
    _ready_contact(client)
    _incoming(client, "hey")
    assert client.get("/whatsapp/outbound").json()[0]["status"] == "pending"

    client.post("/whatsapp/emergency-stop")

    outbound = client.get("/whatsapp/outbound").json()
    assert outbound[0]["status"] == "cancelled"
    assert "emergency stop" in outbound[0]["last_error"]


def test_emergency_stop_prevents_the_sender_from_collecting_anything(
    client: TestClient, ingest_secret
) -> None:
    """Last line: even if a message survived, handover refuses it."""
    _ready_contact(client)
    _incoming(client, "hey")
    client.post("/whatsapp/emergency-stop")

    claimed = client.post(
        "/whatsapp/outbound/claim",
        headers={"X-ARIA-Ingest-Secret": ingest_secret},
    ).json()
    assert claimed["messages"] == []


def test_no_new_autonomous_sends_while_stopped(client: TestClient) -> None:
    _ready_contact(client)
    client.post("/whatsapp/emergency-stop")

    _incoming(client, "hey")
    assert client.get("/whatsapp/autonomous").json() == []
    assert client.get("/whatsapp/outbound").json() == []


def test_pausing_aria_stops_sending_but_keeps_observing(client: TestClient) -> None:
    contact_id = _ready_contact(client)
    client.post("/whatsapp/pause")

    _incoming(client, "hey")
    assert client.get("/whatsapp/outbound").json() == []
    # Still learning: the message was stored.
    assert client.get(f"/whatsapp/contacts/{contact_id}/messages").json()


def test_stop_autonomy_downgrades_to_asking_rather_than_silence(
    client: TestClient,
) -> None:
    """"Keep helping, but check with me" — a different intent from "stop"."""
    _ready_contact(client)
    client.post("/whatsapp/stop-autonomy")

    _incoming(client, "hey")
    assert client.get("/whatsapp/outbound").json() == []
    # A draft is still prepared for him.
    assert client.get("/whatsapp/drafts").json()


def test_resuming_restores_the_previous_mode(client: TestClient) -> None:
    _ready_contact(client)
    client.post("/whatsapp/pause")
    resumed = client.post("/whatsapp/pause?resume=true").json()
    assert resumed["paused"] is False
    assert resumed["mode"] == "limited_autonomy"  # not reset to observe


# ---------- per-contact controls ----------

def test_pausing_one_contact_leaves_the_others_autonomous(
    client: TestClient,
) -> None:
    john = _ready_contact(client, handle="john@s.whatsapp.net")
    mary = client.post(
        "/whatsapp/contacts",
        json={"name": "Mary", "handle": "mary@s.whatsapp.net", "relationship": "friend"},
    ).json()
    client.patch(f"/whatsapp/contacts/{mary['id']}", json={"trust_level": "high"})
    client.patch(
        f"/whatsapp/contacts/{mary['id']}",
        json={"autonomy_enabled": True, "allowed_actions": ["greeting"]},
    )

    client.post(f"/whatsapp/contacts/{john}/pause")

    _incoming(client, "hey", handle="john@s.whatsapp.net")
    client.post(
        "/whatsapp/simulate",
        json={"handle": "mary@s.whatsapp.net", "name": "Mary", "body": "hey"},
    )

    handles = [m["handle"] for m in client.get("/whatsapp/outbound").json()]
    assert "john@s.whatsapp.net" not in handles
    assert "mary@s.whatsapp.net" in handles


def test_taking_over_stops_aria_and_cancels_what_is_queued(
    client: TestClient,
) -> None:
    contact_id = _ready_contact(client)
    _incoming(client, "hey")
    assert client.get("/whatsapp/outbound").json()[0]["status"] == "pending"

    client.post(f"/whatsapp/contacts/{contact_id}/take-over")

    assert client.get("/whatsapp/outbound").json()[0]["status"] == "cancelled"

    # And no NEW autonomous reply is produced for the next message.
    before = len(client.get("/whatsapp/autonomous").json())
    _incoming(client, "you there?")
    assert len(client.get("/whatsapp/autonomous").json()) == before


def test_aria_does_not_resume_a_taken_over_conversation_on_her_own(
    client: TestClient,
) -> None:
    """Only an explicit release brings her back — no timeout, no judgement."""
    contact_id = _ready_contact(client)
    client.post(f"/whatsapp/contacts/{contact_id}/take-over")

    for message in ("hey", "you around?", "hello?", "ok nevermind"):
        _incoming(client, message)
    assert client.get("/whatsapp/outbound").json() == []

    client.post(f"/whatsapp/contacts/{contact_id}/take-over?release=true")
    _incoming(client, "hey again")
    assert client.get("/whatsapp/outbound").json()


# ---------- the execution-time re-check ----------

def test_permission_withdrawn_after_approval_blocks_the_send(
    client: TestClient,
) -> None:
    """A stale approval must fail closed.

    Simulates the race directly: the gateway request exists and is approved,
    and permission is revoked before the executor runs.
    """
    from src.whatsapp import sending

    contact_id = _ready_contact(client)
    contact = next(
        c for c in client.get("/whatsapp/contacts").json() if c["id"] == contact_id
    )

    # Revoke permission, then run the executor with a payload that was built
    # while permission still existed.
    client.post(f"/whatsapp/contacts/{contact_id}/take-over")

    async def _execute():
        import src.db as db_module

        original = db_module.SessionMaker
        db_module.SessionMaker = client.session_maker
        sending.SessionMaker = client.session_maker
        try:
            await sending.execute_whatsapp_send(
                {
                    "contact_id": contact_id,
                    "handle": contact["handle"],
                    "body": "hey, all good",
                    "origin": "autonomous",
                    "incoming": "hey",
                    "action_request_id": "stale-request",
                }
            )
        finally:
            db_module.SessionMaker = original
            sending.SessionMaker = original

    try:
        asyncio.run(_execute())
        raise AssertionError("a withdrawn permission must block the send")
    except sending.SendBlocked as exc:
        assert "taken over" in str(exc)

    assert client.get("/whatsapp/outbound").json() == []


# ---------- delivery confirmation ----------

def test_the_sender_claims_and_confirms_and_it_is_all_audited(
    client: TestClient, ingest_secret
) -> None:
    _ready_contact(client)
    _incoming(client, "hey")

    claimed = client.post(
        "/whatsapp/outbound/claim",
        headers={"X-ARIA-Ingest-Secret": ingest_secret},
    ).json()["messages"]
    assert len(claimed) == 1

    client.post(
        "/whatsapp/outbound/confirm",
        json={"id": claimed[0]["id"], "ok": True},
        headers={"X-ARIA-Ingest-Secret": ingest_secret},
    )

    assert client.get("/whatsapp/outbound").json()[0]["status"] == "sent"
    assert client.get("/whatsapp/autonomous").json()[0]["send_status"] == "sent"


def test_a_failed_send_is_recorded_not_silently_dropped(
    client: TestClient, ingest_secret
) -> None:
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

    outbound = client.get("/whatsapp/outbound").json()[0]
    assert outbound["status"] == "failed"
    assert "socket closed" in outbound["last_error"]


def test_the_outbound_queue_requires_the_shared_secret(client: TestClient) -> None:
    assert client.post("/whatsapp/outbound/claim").status_code in (401, 503)


# ---------- learning from autonomous responses ----------

def test_a_correction_teaches_and_counts_against_reliability(
    client: TestClient,
) -> None:
    _ready_contact(client)
    _incoming(client, "hey")
    response_id = client.get("/whatsapp/autonomous").json()[0]["id"]

    result = client.post(
        f"/whatsapp/autonomous/{response_id}/react",
        json={
            "reaction": "corrected",
            "correction": "yeah bro sawa, niko hapa",
            "note": "too formal",
        },
    ).json()

    assert result["reaction"] == "corrected"
    assert result["lessons"], "a correction must produce a lesson"

    stored = client.get("/whatsapp/autonomous").json()[0]
    assert stored["user_reaction"] == "corrected"
    assert stored["correction"] == "yeah bro sawa, niko hapa"


def test_silence_is_not_treated_as_approval(client: TestClient) -> None:
    """The rule the directive is explicit about.

    An unreviewed response must not count as a success — otherwise ARIA grows
    more confident the less attention MORICE pays, which is backwards.
    """
    _ready_contact(client)
    _incoming(client, "hey")

    stored = client.get("/whatsapp/autonomous").json()[0]
    assert stored["user_reaction"] == "none"

    activity = client.get("/whatsapp/activity").json()
    assert activity["autonomous"]["approved_by_user"] == 0
    assert activity["autonomous"]["unreviewed"] >= 0

    # And it is excluded from the correction rate rather than counted as good.
    from src.whatsapp import decision

    contact_id = client.get("/whatsapp/autonomous").json()[0]["contact_id"]
    reviewed, rate = _run(
        client, lambda s: decision.correction_history(s, contact_id)
    )
    assert reviewed == 0 and rate == 0.0


def test_an_explicit_approval_is_stronger_evidence_than_silence(
    client: TestClient,
) -> None:
    _ready_contact(client)
    _incoming(client, "hey")
    response_id = client.get("/whatsapp/autonomous").json()[0]["id"]
    client.post(
        f"/whatsapp/autonomous/{response_id}/react", json={"reaction": "approved"}
    )

    from src.whatsapp import decision

    contact_id = client.get("/whatsapp/autonomous").json()[0]["contact_id"]
    reviewed, rate = _run(
        client, lambda s: decision.correction_history(s, contact_id)
    )
    assert reviewed == 1  # now it counts
    assert rate == 0.0


def test_repeated_corrections_withdraw_autonomy_automatically(
    client: TestClient,
) -> None:
    """Degrading on evidence is allowed; PROMOTING on evidence is not."""
    _ready_contact(client)

    for index in range(5):
        _incoming(client, f"hey {index}")
        responses = client.get("/whatsapp/autonomous").json()
        client.post(
            f"/whatsapp/autonomous/{responses[0]['id']}/react",
            json={"reaction": "corrected", "correction": "not like that"},
        )

    evaluated = client.post(
        "/whatsapp/evaluate",
        json={"handle": "john@s.whatsapp.net", "body": "hey"},
    ).json()
    assert evaluated["decision"] == "suggest"
    assert "corrected" in evaluated["reasons"][0]
