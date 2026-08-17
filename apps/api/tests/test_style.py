"""Tests for communication style learning.

The guarantees that matter:
  * statistics are real (countable, reproducible), never invented
  * one message can never become a confident rule
  * explicit instructions from MORICE outrank inferred patterns
  * only HIS messages shape his voice — never the other person's
  * everything learned is inspectable and deletable
"""

from fastapi.testclient import TestClient

from src.communication.learning import confidence_for
from src.communication.style import analyze, diff_summary


# ---------- statistics are real ----------

def test_empty_input_yields_no_style() -> None:
    """An unknown voice must look unknown, not average."""
    m = analyze([])
    assert m.sample_size == 0 and m.avg_words == 0.0


def test_counts_are_accurate() -> None:
    m = analyze(["one two three", "four five"])
    assert m.sample_size == 2
    assert m.avg_words == 2.5  # (3 + 2) / 2


def test_detects_greetings_and_rates() -> None:
    m = analyze(["hey bro how are you?", "hey man you good?", "Hello there."])
    assert m.greetings[0][0] == "hey" and m.greetings[0][1] == 2
    assert m.question_rate > 0.6  # two of three end in a question
    assert m.lowercase_start_rate > 0.6  # two of three start lowercase


def test_detects_kiswahili_and_mixing() -> None:
    m = analyze(["Habari yako, are we still meeting?", "Asante for the update"])
    assert m.swahili_rate == 1.0
    assert m.mixed_language_rate == 1.0  # Kiswahili markers plus English


def test_emoji_rate() -> None:
    m = analyze(["nice 👍", "ok", "great 🎉", "sure"])
    assert m.emoji_rate == 0.5


def test_one_off_phrases_are_not_treated_as_habits() -> None:
    """Anti-overfit: a phrase said once is not a verbal habit."""
    m = analyze(["completely unique wording here"])
    assert m.common_phrases == []


def test_repeated_phrases_are_captured() -> None:
    m = analyze(["just checking in", "just checking on this", "just checking again"])
    assert any("just checking" in p for p, _ in m.common_phrases)


# ---------- the confidence curve ----------

def test_confidence_grows_but_never_certain() -> None:
    assert confidence_for(0) == 0.0
    assert confidence_for(1) < 0.2      # one sample is nearly worthless
    assert confidence_for(8) < 0.6
    assert confidence_for(100) > 0.85
    assert confidence_for(10_000) <= 0.95  # never fully certain


def test_confidence_is_monotonic() -> None:
    values = [confidence_for(n) for n in range(0, 60)]
    assert values == sorted(values)


# ---------- learning from edits ----------

def test_diff_detects_shortening_and_emoji() -> None:
    lessons = diff_summary(
        "Hello, I hope this message finds you well and that you are doing fine.",
        "hey 👋",
    )
    assert any("shorter" in l for l in lessons)
    assert any("emoji" in l for l in lessons)


def test_diff_detects_greeting_preference() -> None:
    lessons = diff_summary("Hello there, are you free?", "hey are you free?")
    assert any("'hey'" in l for l in lessons)


def test_diff_of_identical_text_learns_nothing() -> None:
    assert diff_summary("same text here", "same text here") == []


# ---------- endpoints ----------

def test_profile_is_honest_when_nothing_learned(client: TestClient) -> None:
    body = client.get("/style").json()
    assert body["patterns"] == []
    assert "No style profile yet" in body["prompt_block"]


def test_learns_only_from_messages_morice_wrote(client: TestClient) -> None:
    """Inbound messages are other people's voices and must not shape his."""
    # An inbound message with a very distinctive style.
    client.post(
        "/whatsapp/simulate",
        json={"handle": "x@s.whatsapp.net", "name": "Other",
              "body": "GREETINGS ESTEEMED COLLEAGUE I TRUST YOU FARE WELL",
              "direction": "in"},
    )
    refreshed = client.post("/style/refresh").json()
    assert refreshed["dimensions"] == {}, "inbound message must not train his style"

    # Now one he wrote himself.
    client.post(
        "/whatsapp/simulate",
        json={"handle": "x@s.whatsapp.net", "name": "Other",
              "body": "hey bro, sawa see you then", "direction": "out"},
    )
    refreshed = client.post("/style/refresh").json()
    assert refreshed["dimensions"] != {}
    assert refreshed["sample_size"] == 1


def test_single_message_yields_low_confidence(client: TestClient) -> None:
    """The anti-overfit guarantee, end to end."""
    client.post(
        "/whatsapp/simulate",
        json={"handle": "y@s.whatsapp.net", "name": "Y", "body": "yo", "direction": "out"},
    )
    client.post("/style/refresh")
    patterns = client.get("/style").json()["patterns"]
    assert patterns, "should have learned something"
    assert all(p["confidence"] < 0.2 for p in patterns), "one message must stay weak"
    # And weak patterns must not be presented to the model as fact.
    assert "No style profile yet" in client.get("/style").json()["prompt_block"]


def test_explicit_rule_is_trusted_immediately(client: TestClient) -> None:
    created = client.post(
        "/style/rules", json={"rule": "Never use 'Dear Sir/Madam'"}
    ).json()
    assert created["confidence"] >= 0.9
    assert created["source"] == "explicit"

    block = client.get("/style").json()["prompt_block"]
    assert "EXPLICIT RULES" in block and "Dear Sir/Madam" in block


def test_edit_feedback_produces_visible_lessons(client: TestClient) -> None:
    res = client.post(
        "/style/feedback",
        json={
            "kind": "edited",
            "draft": "Hello, I hope this message finds you well.",
            "final": "hey bro",
        },
    ).json()
    assert res["recorded"] is True
    assert res["lessons"], "an edit must produce a visible lesson"


def test_repeated_edits_increase_confidence(client: TestClient) -> None:
    payload = {
        "kind": "edited",
        "draft": "Hello, I hope this message finds you well and all is fine.",
        "final": "hey",
    }
    for _ in range(6):
        client.post("/style/feedback", json=payload)

    prefs = [
        p for p in client.get("/style").json()["patterns"]
        if p["dimension"].startswith("edit:")
    ]
    assert prefs, "repeated edits should form a preference"
    assert max(p["evidence_count"] for p in prefs) == 6, "evidence must accumulate"
    # Six consistent edits is real signal, so it should now be usable.
    assert max(p["confidence"] for p in prefs) > 0.25
    assert "shorter" in client.get("/style").json()["prompt_block"]


def test_invalid_feedback_kind_rejected(client: TestClient) -> None:
    r = client.post("/style/feedback", json={"kind": "vibes"})
    assert r.status_code == 422


def test_patterns_can_be_forgotten(client: TestClient) -> None:
    created = client.post("/style/rules", json={"rule": "Always sign off 'Morice'"}).json()
    assert client.delete(f"/style/patterns/{created['id']}").status_code == 204
    assert client.delete(f"/style/patterns/{created['id']}").status_code == 404
    assert "Morice" not in client.get("/style").json()["prompt_block"]


def test_preview_lessons_does_not_record(client: TestClient) -> None:
    res = client.post(
        "/style/preview-lessons",
        json={"draft": "Hello there my friend, how do you do?", "final": "yo"},
    ).json()
    assert res["recorded"] is False and res["lessons"]
    # Nothing was stored.
    assert client.get("/style").json()["patterns"] == []


def test_dimension_keys_fit_the_database_column(client: TestClient) -> None:
    """Regression: SQLite ignores VARCHAR limits, Postgres does not.

    A long edit-lesson produced a dimension key longer than the column and
    Postgres rejected the insert at runtime while the test suite stayed
    green. Assert the length explicitly so the check does not depend on
    which database the tests happen to run against.
    """
    from src.communication.learning import MAX_DIMENSION_LEN

    long_draft = (
        "Good afternoon, I trust this correspondence finds you in excellent "
        "health and high spirits on this most agreeable of days."
    )
    client.post(
        "/style/feedback",
        json={"kind": "edited", "draft": long_draft, "final": "yo"},
    )
    client.post("/style/rules", json={"rule": "x" * 400})

    for p in client.get("/style").json()["patterns"]:
        assert len(p["dimension"]) <= MAX_DIMENSION_LEN, (
            f"dimension {p['dimension']!r} exceeds the column width"
        )


# ---------- teaching ARIA a voice from real writing ----------

def test_all_of_morices_own_writing_counts_as_evidence(client: TestClient) -> None:
    """Outbound messages, his corrections, and pasted samples are all his.

    Corrections in particular were previously used only to derive "prefers
    shorter" lessons and were not counted as writing at all - throwing away
    the most deliberate example of how he wanted a message to read.
    """
    client.post(
        "/whatsapp/simulate",
        json={
            "handle": "friend@s.whatsapp.net",
            "name": "Friend",
            "body": "hey bro sawa",
            "direction": "out",
        },
    )
    client.post(
        "/style/feedback",
        json={"kind": "edited", "draft": "Good afternoon.", "final": "yo, sawa"},
    )
    client.post("/style/samples", json={"text": "hey man\njust checking in"})

    before = client.get("/style/readiness").json()
    assert before["samples"] >= 4  # 1 message + 1 correction + 2 samples


def test_chat_messages_to_aria_are_not_used_as_voice_evidence(
    client: TestClient,
) -> None:
    """A different register. Blending it would make ARIA's WhatsApp voice
    sound like his talking-to-an-assistant voice."""
    conversation = client.post("/conversations").json()
    client.post(
        f"/conversations/{conversation['id']}/messages",
        json={"content": "Could you please summarise this document for me?"},
    )
    assert client.get("/style/readiness").json()["samples"] == 0


def test_a_pasted_block_counts_as_many_samples_not_one(client: TestClient) -> None:
    """Otherwise 'average words per message' measures the size of his paste."""
    client.post(
        "/style/samples",
        json={"text": "hey\nyou around?\nsawa see you at 5\njust checking"},
    )
    assert client.get("/style/readiness").json()["samples"] == 4


def test_samples_report_how_many_more_are_needed(client: TestClient) -> None:
    """A visible finish line, rather than 'keep going'."""
    result = client.post("/style/samples", json={"text": "hey\nsawa"}).json()
    assert result["added"] == 2
    assert result["ready_for_autonomy"] is False
    assert result["samples_needed"] if "samples_needed" in result else True
    assert "more of your messages" in result["note"]


def test_enough_real_samples_reach_the_autonomy_threshold(
    client: TestClient,
) -> None:
    """The full path: paste real messages, cross the confidence gate.

    This is what makes autonomy reachable on a fresh install without waiting
    weeks for conversation to accumulate.
    """
    messages = "\n".join(
        [
            "hey bro, sawa see you at 5",
            "yo just checking if you got the file",
            "hey man, asante for the help",
            "just checking in on this one",
            "sawa, tutaonana kesho",
            "hey, you free later?",
            "yo bro just checking the status",
            "asante sana, appreciate it",
            "hey, sawa lets do it tomorrow",
            "just checking, did it work?",
            "sawa cool, see you then",
            "hey, did you sort it out?",
            "yo, all good on my side",
            "asante, that helps a lot",
            "hey, running late a bit",
            "sawa no problem at all",
            "just checking you got home",
            "hey bro, how did it go?",
            "yo, lets catch up soon",
            "sawa, talk later",
            "hey, sounds good to me",
            "just confirming for tomorrow",
        ]
    )
    result = client.post("/style/samples", json={"text": messages}).json()

    assert result["ready_for_autonomy"] is True, result["note"]
    assert client.get("/style/readiness").json()["ready_for_autonomy"] is True


def test_readiness_reports_the_number_the_engine_actually_gates_on(
    client: TestClient,
) -> None:
    """A dashboard showing a different figure from the gate is worse than none."""
    import asyncio

    client.post("/style/samples", json={"text": "hey\nsawa\nyo bro"})

    from src.whatsapp import decision

    async def _engine_value():
        async with client.session_maker() as session:
            return await decision.communication_confidence(session)

    assert client.get("/style/readiness").json()["confidence"] == asyncio.run(
        _engine_value()
    )


def test_empty_samples_are_refused(client: TestClient) -> None:
    assert client.post("/style/samples", json={"text": "   \n  \n"}).status_code == 422
