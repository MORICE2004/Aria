"""Research agent tests.

The failure this agent must never have: answering beyond its evidence. A
research agent that quietly fills gaps from training data is worse than none,
because its confident wrong answers look exactly like its correct ones.

So the tests care most about honesty — that an empty search says so, that the
scope limitation is always stated, and that evidence is never double-counted
into looking better supported than it is.
"""

from __future__ import annotations

import io

from fastapi.testclient import TestClient

from src.research.sources import _excerpt_around, _keywords


def _upload(client: TestClient, name: str, content: bytes):
    return client.post(
        "/documents",
        files={"file": (name, io.BytesIO(content), "text/plain")},
    )


def _research(client: TestClient, question: str, **kwargs):
    return client.post(
        "/research", json={"question": question, **kwargs}
    ).json()


# ---------- honesty about scope ----------

def test_a_question_with_no_evidence_says_so_plainly(client: TestClient) -> None:
    """An empty search must not produce a fluent essay."""
    report = _research(client, "What is the capital of Mongolia?")

    assert report["evidence"] == []
    assert "nothing on this" in report["answer"]
    # And it explains the limitation rather than leaving it mysterious.
    assert "cannot search the web" in report["answer"]


def test_every_report_states_that_aria_cannot_browse(client: TestClient) -> None:
    """The most misleading thing a research agent can do is look like it
    searched the internet when it did not."""
    report = _research(client, "anything at all")
    assert "no web access" in report["scope_note"]


def test_the_sources_endpoint_makes_the_limitation_discoverable(
    client: TestClient,
) -> None:
    sources = client.get("/research/sources").json()
    assert "web" in sources["unavailable"]
    assert "memory" in sources["available"]
    assert "documents" in sources["available"]
    assert "SourceProvider" in sources["note"]  # tells you how to fix it


# ---------- finding real evidence ----------

def test_research_finds_evidence_in_memory(client: TestClient) -> None:
    # The test embedder scores by word overlap (see conftest), so the query
    # here shares vocabulary with the stored text and clears the agent's
    # MIN_RELEVANCE floor. Embedding QUALITY is tested in test_memory.py;
    # this test is about the research pipeline.
    client.post(
        "/memory",
        json={
            "title": "Career goal",
            "content": "MORICE wants to become a backend developer working in Python.",
            "kind": "fact",
        },
    )

    report = _research(client, "backend developer working Python")
    assert report["evidence"]
    assert any("memory" == e["source"] for e in report["evidence"])
    assert any("Career goal" in e["citation"] for e in report["evidence"])


def test_research_finds_evidence_in_documents(client: TestClient) -> None:
    _upload(
        client,
        "contract.txt",
        b"EMPLOYMENT TERMS\n\nThe notice period is thirty days from signature.",
    )

    report = _research(client, "What is the notice period in my contract?")
    citations = " ".join(e["citation"] for e in report["evidence"])
    assert "contract.txt" in citations


def test_research_finds_evidence_in_conversations(client: TestClient) -> None:
    """A lot of what MORICE knows arrived as a WhatsApp message."""
    client.post(
        "/whatsapp/simulate",
        json={
            "handle": "grace@s.whatsapp.net",
            "name": "Grace",
            "body": "The Nairobi conference is confirmed for November.",
        },
    )

    report = _research(client, "When is the Nairobi conference?")
    assert any(e["source"] == "conversations" for e in report["evidence"])
    assert any("Grace" in e["citation"] for e in report["evidence"])


def test_every_piece_of_evidence_is_attributable(client: TestClient) -> None:
    """A finding ARIA cannot attribute is one she should not report."""
    client.post(
        "/memory",
        json={"title": "Visa status", "content": "Schengen visa expires in March.", "kind": "fact"},
    )
    report = _research(client, "Schengen visa expires")
    for evidence in report["evidence"]:
        assert evidence["citation"].strip()
        assert evidence["source"].strip()


# ---------- not overstating support ----------

def test_the_same_passage_found_twice_counts_once(client: TestClient) -> None:
    """Sub-questions overlap, so the same passage comes back repeatedly.

    Counting it three times would make one supported claim look like three.
    """
    client.post(
        "/memory",
        json={
            "title": "Visa",
            "content": "The Schengen visa application deadline is the 30th of March.",
            "kind": "fact",
        },
    )

    report = _research(client, "Schengen visa application deadline March")
    contents = [e["content"] for e in report["evidence"]]
    assert len(contents) == len(set(contents))


def test_irrelevant_evidence_is_excluded(client: TestClient) -> None:
    """Weak matches make the prompt longer and the answer worse."""
    client.post(
        "/memory",
        json={"title": "Groceries", "content": "Buy milk and bread.", "kind": "note"},
    )
    report = _research(client, "What does my employment contract say about notice?")
    assert not any("milk" in e["content"] for e in report["evidence"])


# ---------- robustness ----------

def test_a_failing_source_does_not_fail_the_research(
    client: TestClient, monkeypatch
) -> None:
    """A broken document index should cost some evidence, not the answer."""
    client.post(
        "/memory",
        json={"title": "Goal", "content": "Become a backend developer.", "kind": "fact"},
    )

    from src.research import sources as sources_module

    async def explode(self, session, query, *, limit=5):
        raise RuntimeError("document index unavailable")

    monkeypatch.setattr(sources_module.DocumentSource, "search", explode)

    report = _research(client, "backend developer")
    assert report["evidence"]  # memory still contributed


def test_an_unusable_plan_falls_back_to_the_question(client: TestClient) -> None:
    """Planning is a convenience; its failure must not fail the research."""
    client.post(
        "/memory",
        json={"title": "Goal", "content": "Become a backend developer.", "kind": "fact"},
    )
    # depth=1 skips planning entirely — the same path a bad plan degrades to.
    report = _research(client, "backend developer", depth=1)
    assert report["sub_questions"] == []
    assert report["evidence"]


def test_findings_can_be_remembered_with_provenance(client: TestClient) -> None:
    client.post(
        "/memory",
        json={"title": "Goal", "content": "Become a backend developer.", "kind": "fact"},
    )
    report = _research(client, "backend developer", remember=True)
    assert report["remembered"] is True

    notes = [i for i in client.get("/memory").json() if i["kind"] == "note"]
    research_note = next(n for n in notes if n["title"].startswith("Research:"))
    assert "ARIA researched this" in research_note["provenance"]


def test_nothing_is_remembered_when_nothing_was_found(client: TestClient) -> None:
    """Storing an empty answer would pollute memory with ARIA's own ignorance."""
    report = _research(client, "What is the airspeed of a swallow?", remember=True)
    assert report["remembered"] is False


# ---------- helpers ----------

def test_stopwords_are_stripped_from_search_terms() -> None:
    """Without this, every question matches every document."""
    terms = _keywords("What does my contract say about the notice period?")
    assert "contract" in terms and "notice" in terms
    assert "what" not in terms and "the" not in terms


def test_an_excerpt_is_a_window_not_the_whole_document() -> None:
    """A citation the size of a contract is not a citation."""
    text = "padding " * 500 + "the notice period is thirty days " + "padding " * 500
    excerpt = _excerpt_around(text, "notice")
    assert "notice period" in excerpt
    assert len(excerpt) < 600
    assert excerpt.startswith("…")
