"""Tests for the commands ARIA answers herself.

The risk in this feature is not that a command fails to fire — that costs a
click. It is that an ordinary sentence fires one, which silently does something
MORICE did not ask for. Most of these tests are therefore about what must NOT
be treated as a command.
"""

from fastapi.testclient import TestClient


def _say(client: TestClient, text: str) -> str:
    conversation = client.post("/conversations").json()
    response = client.post(
        f"/conversations/{conversation['id']}/messages", json={"content": text}
    )
    assert response.status_code == 200
    return response.text


# ---------- what must NOT be a command ----------

def test_a_sentence_about_stopping_is_not_the_kill_switch(
    client: TestClient,
) -> None:
    """The failure that would matter: an ordinary sentence stopping ARIA."""
    reply = _say(client, "I really need to stop saying yes to everything")
    assert "Emergency stop" not in reply
    assert client.get("/whatsapp/autonomy").json()["emergency_stop"] is False


def test_asking_about_the_stop_control_does_not_press_it(
    client: TestClient,
) -> None:
    reply = _say(client, "what does the emergency stop actually do to the queue?")
    assert "Emergency stop is on" not in reply
    assert client.get("/whatsapp/autonomy").json()["emergency_stop"] is False


def test_a_long_message_beginning_with_a_command_word_is_a_sentence(
    client: TestClient,
) -> None:
    long_message = (
        "stop me if this is a bad idea, but I was thinking about how the "
        "outbound queue works and whether it would be better to push instead "
        "of poll, given that the sender already re-checks the stop controls"
    )
    _say(client, long_message)
    assert client.get("/whatsapp/autonomy").json()["emergency_stop"] is False


def test_ordinary_questions_still_reach_the_model(client: TestClient) -> None:
    reply = _say(client, "what is a database index?")
    assert "Echo:" in reply  # the fake model answered, not a command


# ---------- what must be a command ----------

def test_stop_stops(client: TestClient) -> None:
    reply = _say(client, "ARIA, stop")
    assert "Emergency stop is on" in reply

    state = client.get("/whatsapp/autonomy").json()
    assert state["emergency_stop"] is True
    assert state["mode"] == "observe"


def test_stop_replying_to_whatsapp_stops(client: TestClient) -> None:
    _say(client, "stop replying to whatsapp")
    assert client.get("/whatsapp/autonomy").json()["emergency_stop"] is True


def test_stopping_cancels_what_was_already_queued(
    client: TestClient, auth_enabled
) -> None:
    """A kill switch that leaves an approved message in the queue is not one."""
    from tests.test_sending import _incoming, _ready_contact

    _ready_contact(client)
    _incoming(client, "hey")
    assert client.get("/whatsapp/outbound").json()[0]["status"] == "pending"

    _say(client, "stop")

    assert client.get("/whatsapp/outbound").json()[0]["status"] == "cancelled"


def test_pause_pauses_without_losing_the_configuration(client: TestClient) -> None:
    client.patch("/whatsapp/autonomy", json={"mode": "suggest"})
    reply = _say(client, "ARIA, pause")

    state = client.get("/whatsapp/autonomy").json()
    assert state["paused"] is True
    assert state["mode"] == "suggest"  # untouched, so resuming restores it
    assert "untouched" in reply


def test_aria_refuses_to_restart_herself_on_a_typed_word(
    client: TestClient,
) -> None:
    """Stopping is instant; starting again is deliberate. Never the reverse."""
    _say(client, "stop")
    reply = _say(client, "ARIA, resume")

    assert "will not start myself" in reply
    assert client.get("/whatsapp/autonomy").json()["emergency_stop"] is True


# ---------- briefing ----------

def test_the_briefing_command_reports_a_quiet_period_honestly(
    client: TestClient,
) -> None:
    reply = _say(client, "ARIA, briefing")
    assert "Nothing happened" in reply
    assert "not leaving anything out" in reply


def test_the_briefing_command_reports_real_activity(client: TestClient) -> None:
    client.post(
        "/whatsapp/simulate",
        json={"handle": "ann@s.whatsapp.net", "name": "Ann", "body": "hey"},
    )
    reply = _say(client, "what did I miss?")
    assert "Messages that came in" in reply
    assert "Ann" in reply


def test_several_phrasings_reach_the_briefing(client: TestClient) -> None:
    for phrasing in (
        "briefing",
        "brief me",
        "ARIA, what happened while I was away",
        "catch me up",
        "what have you been doing today",
    ):
        assert "Nothing happened" in _say(client, phrasing), phrasing


# ---------- explaining a send ----------

def test_why_did_you_send_that_explains_from_the_record(
    client: TestClient, auth_enabled
) -> None:
    from tests.test_sending import _incoming, _ready_contact

    _ready_contact(client)
    _incoming(client, "hey")

    reply = _say(client, "why did you send that?")

    assert "John" in reply  # the contact the helper configures
    assert "Risk" in reply
    assert "confidence" in reply.lower()
    # Queued is not sent, and the explanation must say so.
    assert "NOT been delivered" in reply


def test_why_did_you_send_that_admits_when_there_is_nothing_to_explain(
    client: TestClient,
) -> None:
    reply = _say(client, "why did you send that?")
    assert "not replied to anyone on my own yet" in reply


def test_a_command_reply_is_stored_in_the_conversation(client: TestClient) -> None:
    """It must read back like any other exchange, not vanish from history."""
    conversation = client.post("/conversations").json()
    client.post(
        f"/conversations/{conversation['id']}/messages", json={"content": "briefing"}
    )

    messages = client.get(f"/conversations/{conversation['id']}/messages").json()
    assert [m["role"] for m in messages] == ["user", "assistant"]
    assert "Nothing happened" in messages[1]["content"]


def test_a_command_costs_nothing(client: TestClient) -> None:
    """Answered from records, so no model call and no spend."""
    _say(client, "briefing")
    assert client.get("/costs").json()["totals"]["today"]["calls"] == 0
