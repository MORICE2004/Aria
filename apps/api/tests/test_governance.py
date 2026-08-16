"""Tests for memory governance.

ARIA must not hoard. These pin down what gets kept, for how long, and — most
importantly — that MORICE's explicit intent always wins over a heuristic.
"""

from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient

from src.memory.governance import MEMORY_TYPES, is_expired, judge


def test_explicit_request_overrides_every_heuristic() -> None:
    """He said remember it. ARIA does not second-guess that."""
    v = judge(title="x", content="tonight only", kind="note", explicit=True)
    assert v.memory_type == "longterm"
    assert v.importance >= 0.9
    assert v.expires_at is None
    assert "you asked" in v.reason


def test_transient_wording_is_short_lived() -> None:
    v = judge(title="Reminder", content="waiting for the bus right now", kind="note")
    assert v.memory_type == "transient"
    assert v.expires_at is not None
    assert v.importance <= 0.35


def test_style_samples_are_durable_preferences() -> None:
    v = judge(title="How I write", content="hey bro sawa", kind="style")
    assert v.memory_type == "preference"
    assert v.expires_at is None


def test_very_short_notes_score_low() -> None:
    assert judge(title="x", content="ok", kind="note").importance <= 0.35


def test_substantial_documents_score_higher() -> None:
    long_doc = " ".join(["experience"] * 250)
    assert judge(title="CV", content=long_doc, kind="document").importance > 0.7


def test_every_judgement_explains_itself() -> None:
    """A score nobody can explain is a score nobody should trust."""
    for kind in ("note", "fact", "document", "style"):
        v = judge(title="t", content="some ordinary content here", kind=kind)
        assert v.reason, f"{kind} judgement had no reason"
        assert v.memory_type in MEMORY_TYPES


def test_expiry_check_handles_naive_timestamps() -> None:
    """SQLite hands back naive datetimes; treating them as UTC avoids a crash."""
    past = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=1)
    assert is_expired(past) is True
    assert is_expired(None) is False


# ---------- endpoints ----------

def test_memory_records_type_importance_and_provenance(client: TestClient) -> None:
    created = client.post(
        "/memory",
        json={"title": "Career goal", "content": "Become a backend developer.",
              "kind": "fact"},
    ).json()
    assert created["memory_type"] == "longterm"
    assert created["importance"] > 0
    assert created["provenance"], "every memory must explain why it exists"


def test_explicit_memory_is_marked_important(client: TestClient) -> None:
    created = client.post(
        "/memory",
        json={"title": "My birthday", "content": "March 3", "kind": "fact",
              "explicit": True},
    ).json()
    assert created["importance"] >= 0.9
    assert created["expires_at"] is None


def test_listing_is_ordered_by_importance(client: TestClient) -> None:
    client.post("/memory", json={"title": "trivial", "content": "ok", "kind": "note"})
    client.post(
        "/memory",
        json={"title": "important", "content": "This matters a great deal to me",
              "kind": "fact", "explicit": True},
    )
    titles = [m["title"] for m in client.get("/memory").json()]
    assert titles[0] == "important"


def test_expired_memories_are_suggested_not_auto_deleted(client: TestClient) -> None:
    """ARIA proposes forgetting; MORICE decides."""
    client.post(
        "/memory",
        json={"title": "Bus", "content": "waiting for the bus right now",
              "kind": "note"},
    )
    # Not expired yet (7-day lifetime), so nothing is suggested.
    assert client.get("/memory/expired").json() == []
    # And it is still present — nothing was silently removed.
    assert len(client.get("/memory").json()) == 1


def test_prune_reports_exactly_what_it_deleted(client: TestClient) -> None:
    body = client.post("/memory/prune").json()
    assert body["deleted"] == 0 and body["titles"] == []


def test_filter_by_memory_type(client: TestClient) -> None:
    client.post("/memory", json={"title": "S", "content": "hey bro", "kind": "style"})
    client.post("/memory", json={"title": "F", "content": "I live in Nairobi", "kind": "fact"})
    prefs = client.get("/memory", params={"memory_type": "preference"}).json()
    assert [m["title"] for m in prefs] == ["S"]
