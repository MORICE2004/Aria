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


# ---------- remembering ----------

def test_remember_stores_what_he_said(client: TestClient) -> None:
    reply = _say(client, "ARIA, remember that my passport expires in March 2027")

    assert "Remembered" in reply
    stored = client.get("/memory").json()
    assert any("passport expires in March 2027" in m["content"] for m in stored)


def test_remember_carries_a_long_note_intact(client: TestClient) -> None:
    """The 200-character rule protects the kill switch, not the notepad.

    A remember command whose content is a few paragraphs is the ordinary case;
    if the length guard applied to it, the content would be silently dropped
    and answered conversationally instead.
    """
    body = (
        "the landlord agreement says rent is due on the 5th, the deposit is "
        "two months, repairs under 50000 are mine, and the notice period is "
        "sixty days which is longer than the usual thirty so I need to diary "
        "it well before the lease ends in November"
    )
    assert len(body) > 200

    _say(client, f"remember this: {body}")

    stored = client.get("/memory").json()
    assert any(m["content"] == body for m in stored)


def test_a_remembered_note_says_why_it_is_remembered(client: TestClient) -> None:
    """Provenance is what makes a memory trustworthy; it must be set."""
    _say(client, "remember that I prefer morning meetings")

    note = next(
        m for m in client.get("/memory").json() if "morning meetings" in m["content"]
    )
    assert note["provenance"] == "You told me to remember this in chat"


def test_a_word_beginning_with_the_command_is_not_the_command(
    client: TestClient,
) -> None:
    """`remember` must not match the first eight letters of `remembering`."""
    _say(client, "remembering names is genuinely hard for me")
    assert client.get("/memory").json() == []


def test_a_question_about_a_memory_does_not_store_the_question(
    client: TestClient,
) -> None:
    """"Remember what I told you about X?" is a question, not an instruction."""
    _say(client, "remember what I told you about the visa appointment?")
    assert client.get("/memory").json() == []


# ---------- recalling ----------

def test_recall_answers_from_memory(client: TestClient) -> None:
    _say(client, "remember that my landlord is called Hamisi")
    reply = _say(client, "what do you remember about my landlord?")

    assert "Hamisi" in reply
    assert "match" in reply  # each hit is reported with its score


def test_recall_admits_an_empty_memory(client: TestClient) -> None:
    reply = _say(client, "what do you remember about my car insurance?")
    assert "Nothing on" in reply
    assert "remember that" in reply  # tells him how to fix it


def test_recall_costs_nothing(client: TestClient) -> None:
    """Answered from stored records, so nothing can be embellished by a model."""
    _say(client, "remember that the office wifi password is on the router")
    _say(client, "what do you remember about the wifi?")

    assert client.get("/costs").json()["totals"]["today"]["calls"] == 0


# ---------- forgetting ----------

def test_forget_that_undoes_what_was_just_remembered(client: TestClient) -> None:
    _say(client, "remember that I owe Ann 20000")
    assert len(client.get("/memory").json()) == 1

    reply = _say(client, "forget that")

    assert "Forgotten" in reply
    assert client.get("/memory").json() == []


def test_forget_it_is_an_ordinary_phrase_when_nothing_was_remembered(
    client: TestClient,
) -> None:
    """The false positive that would matter: deleting on a change of subject.

    With nothing recently stored from chat, "forget it" must reach the model
    like any other sentence.
    """
    reply = _say(client, "forget it")
    assert "Echo:" in reply
    assert "Forgotten" not in reply


def test_forget_that_will_not_touch_a_memory_aria_learned_elsewhere(
    client: TestClient,
) -> None:
    """Only work this command layer created may be undone by a typed word."""
    client.post(
        "/memory",
        json={
            "title": "From his CV",
            "content": "Five years of logistics experience",
            "kind": "document",
        },
    )

    reply = _say(client, "forget that")

    assert "Echo:" in reply  # fell through; nothing was deleted
    assert len(client.get("/memory").json()) == 1


def test_forgetting_by_subject_lists_but_never_deletes(client: TestClient) -> None:
    """Semantic matching is approximate, so deletion stays a deliberate click."""
    _say(client, "remember that my landlord is called Hamisi")

    reply = _say(client, "forget everything about my landlord")

    assert "will not delete" in reply
    assert "Hamisi" in reply  # shows exactly what it would have taken
    assert len(client.get("/memory").json()) == 1


def test_forgetting_a_subject_it_has_nothing_on_says_so(client: TestClient) -> None:
    reply = _say(client, "forget everything about the boat purchase")
    assert "nothing matching" in reply


# ---------- research ----------

def test_research_reaches_the_research_agent(client: TestClient) -> None:
    """Not the chat model. The tell is the scope note, which only it writes."""
    _say(client, "remember that the deposit on the flat was 240000 shillings")

    reply = _say(client, "research what the flat has cost me so far")

    assert "no web access" in reply
    # Numbered to match the [n] markers the agent writes into the answer.
    assert "Sources, numbered as the answer cites them:" in reply
    assert "[1] your memory:" in reply


def test_research_with_no_evidence_does_not_improvise(client: TestClient) -> None:
    reply = _say(client, "research the history of the Zanzibar clove trade")

    assert "nothing on this" in reply
    assert "cannot search the web" in reply


def test_research_says_it_stored_nothing(client: TestClient) -> None:
    """It costs a model call; it must not also quietly grow his memory."""
    reply = _say(client, "research my rent history")
    assert "Nothing was stored" in reply
    assert client.get("/memory").json() == []


def test_an_ordinary_sentence_is_not_a_research_request(client: TestClient) -> None:
    reply = _say(client, "I should probably research that at some point")
    assert "Echo:" in reply


def test_an_unfinished_command_reaches_the_model(client: TestClient) -> None:
    """The chat page's buttons prefill "remember that " for him to complete.

    Sending it unfinished, or with the placeholder ellipsis still in it, must
    not store a memory whose content is punctuation.
    """
    for unfinished in ("remember that ...", "research ...", "remember that"):
        _say(client, unfinished)
    assert client.get("/memory").json() == []
