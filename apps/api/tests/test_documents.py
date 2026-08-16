"""Document intelligence tests.

The theme: a document assistant that quietly does nothing is worse than one
that refuses. So most of these check that failures are LOUD and specific — a
scanned PDF says it is a scan, an unsupported file names what is supported,
and a model claiming an unsourced fact has that fact discarded.
"""

from __future__ import annotations

import io

import pytest
from fastapi.testclient import TestClient

from src.documents.extract import UnsupportedDocument, extract_text
from src.documents.service import parse_facts


def _upload(client: TestClient, name: str, content: bytes):
    return client.post(
        "/documents", files={"file": (name, io.BytesIO(content), "application/octet-stream")}
    )


def _pdf_bytes(pages: list[str]) -> bytes:
    """A real PDF with a real text layer, built by the same library that reads
    it. Using a hand-rolled fixture would test the fixture, not the code."""
    from pypdf import PdfWriter

    try:
        from reportlab.pdfgen import canvas  # noqa: F401
    except ImportError:
        pytest.skip("reportlab not installed; PDF generation unavailable")

    from reportlab.pdfgen import canvas

    buffer = io.BytesIO()
    pdf = canvas.Canvas(buffer)
    for text in pages:
        pdf.drawString(72, 720, text)
        pdf.showPage()
    pdf.save()
    buffer.seek(0)

    writer = PdfWriter(clone_from=buffer)
    out = io.BytesIO()
    writer.write(out)
    return out.getvalue()


# ---------- extraction ----------

def test_plain_text_is_extracted() -> None:
    result = extract_text(b"Hello MORICE.\n\nThis is a note.", "note.txt")
    assert "Hello MORICE." in result.text
    assert result.format == "txt"


def test_markdown_headings_become_sections() -> None:
    result = extract_text(
        b"# Employment Contract\n\nsome text\n\n## Notice Period\n\n30 days",
        "contract.md",
    )
    assert "Employment Contract" in result.sections
    assert "Notice Period" in result.sections


def test_hyphenated_line_breaks_are_rejoined() -> None:
    """PDF extraction splits words across lines; leaving them breaks search."""
    result = extract_text(b"The notice per-\niod is 30 days.", "x.txt")
    assert "period" in result.text


def test_an_unsupported_file_says_what_is_supported() -> None:
    with pytest.raises(UnsupportedDocument, match="Supported"):
        extract_text(b"\x00\x01binary", "recording.mp4")


def test_an_empty_file_is_refused() -> None:
    with pytest.raises(UnsupportedDocument, match="empty"):
        extract_text(b"   \n  ", "blank.txt")


def test_an_oversized_document_is_refused_with_the_size() -> None:
    from src.documents.extract import MAX_CHARACTERS

    with pytest.raises(UnsupportedDocument, match="over ARIA"):
        extract_text(b"x" * (MAX_CHARACTERS + 10), "huge.txt")


def test_undecodable_bytes_do_not_lose_the_document() -> None:
    """Better mangled accents than a lost file."""
    # latin-1 bytes for accented characters are invalid UTF-8, so this
    # exercises the fallback rather than the happy path.
    raw = "café naïve".encode("latin-1")
    with pytest.raises(UnicodeDecodeError):
        raw.decode("utf-8")
    assert extract_text(raw, "notes.txt").text  # decoded rather than raising


def test_a_pdf_with_no_text_layer_says_so() -> None:
    """The failure that matters most: a scan silently ingesting as empty.

    An empty document looks ingested, searches as nothing, and teaches ARIA
    nothing while appearing to have worked.
    """
    from pypdf import PdfWriter

    writer = PdfWriter()
    writer.add_blank_page(width=200, height=200)
    buffer = io.BytesIO()
    writer.write(buffer)

    with pytest.raises(UnsupportedDocument, match="no readable text"):
        extract_text(buffer.getvalue(), "scan.pdf")


def test_a_corrupt_pdf_fails_with_a_reason() -> None:
    with pytest.raises(UnsupportedDocument, match="could not be opened"):
        extract_text(b"%PDF-1.4 this is not really a pdf", "broken.pdf")


# ---------- storing ----------

def test_uploading_makes_a_document_searchable(client: TestClient) -> None:
    """After upload the document is useful, before any model has run."""
    response = _upload(
        client,
        "cv.txt",
        b"MORICE is a backend developer working with Python and FastAPI.",
    )
    assert response.status_code == 201
    document = response.json()
    assert document["filename"] == "cv.txt"
    assert document["characters"] > 0
    assert document["facts_extracted"] is False  # separate step, on purpose

    hits = client.get("/memory/search?q=backend developer").json()
    assert any("backend developer" in h["content"] for h in hits)


def test_a_stored_document_carries_its_provenance(client: TestClient) -> None:
    """'Why do you know that?' must have an answer that names the file."""
    _upload(client, "contract.txt", b"The notice period is thirty days.")
    items = client.get("/memory").json()
    document_item = next(i for i in items if i["title"] == "contract.txt")
    assert "contract.txt" in document_item.get("provenance", "")


def test_deleting_a_document_also_forgets_it(client: TestClient) -> None:
    """Otherwise ARIA could still quote a document MORICE deleted."""
    document = _upload(client, "secret.txt", b"The passphrase is hunter2 apples.").json()
    assert client.delete(f"/documents/{document['id']}").status_code == 204

    hits = client.get("/memory/search?q=passphrase").json()
    assert not any("hunter2" in h["content"] for h in hits)


def test_an_unreadable_upload_explains_why(client: TestClient) -> None:
    response = _upload(client, "video.mp4", b"\x00\x01\x02")
    assert response.status_code == 422
    assert "Supported" in response.json()["detail"]


def test_an_oversized_upload_is_refused(client: TestClient) -> None:
    from src.routers.documents import MAX_UPLOAD_BYTES

    response = _upload(client, "big.txt", b"x" * (MAX_UPLOAD_BYTES + 1))
    assert response.status_code == 413


# ---------- fact extraction ----------

def test_facts_without_a_supporting_quote_are_discarded() -> None:
    """A fact with no source is not a fact."""
    facts = parse_facts(
        '[{"fact":"MORICE lives in Dar es Salaam","category":"personal"}]'
    )
    assert facts == []


def test_invented_categories_are_normalised() -> None:
    facts = parse_facts(
        '[{"fact":"x is true","category":"TOTALLY_MADE_UP","quote":"a long enough quote here"}]'
    )
    assert facts[0].category == "other"


def test_unusable_model_output_degrades_to_nothing() -> None:
    assert parse_facts("I could not find any facts, sorry.") == []
    assert parse_facts("") == []


def test_a_fact_whose_quote_is_not_in_the_document_is_rejected(
    client: TestClient, monkeypatch
) -> None:
    """The check that separates extraction from fabrication.

    A model inventing a plausible fact is the failure mode that matters, and
    verifying the quote catches it without needing to trust the model.
    """
    document = _upload(
        client, "contract.txt", b"The notice period is thirty days from signature."
    ).json()

    from src.documents import service as service_module

    async def fake_complete(llm, system, user):
        return (
            '[{"fact":"The notice period is thirty days",'
            '"category":"legal","quote":"The notice period is thirty days"},'
            '{"fact":"The salary is 5,000,000 TZS per month",'
            '"category":"financial","quote":"The salary is 5,000,000 TZS per month"}]'
        )

    monkeypatch.setattr(service_module, "_complete", fake_complete)

    facts = client.post(f"/documents/{document['id']}/extract-facts").json()
    # Only the sourced one survives; the invented salary is gone.
    assert len(facts) == 1
    assert "notice period" in facts[0]["fact"]


def test_a_trivially_short_quote_is_not_accepted(client: TestClient, monkeypatch) -> None:
    """A five-character 'quote' matches everything and proves nothing."""
    document = _upload(client, "note.txt", b"MORICE works with Python daily.").json()

    from src.documents import service as service_module

    async def fake_complete(llm, system, user):
        return '[{"fact":"He uses Python","category":"professional","quote":"the"}]'

    monkeypatch.setattr(service_module, "_complete", fake_complete)
    assert client.post(f"/documents/{document['id']}/extract-facts").json() == []


def test_a_proposed_fact_is_not_a_memory_until_accepted(
    client: TestClient, monkeypatch
) -> None:
    """ARIA does not adopt beliefs about MORICE's life because a model read
    them in a PDF."""
    document = _upload(
        client, "cv.txt", b"MORICE has five years of backend engineering experience."
    ).json()

    from src.documents import service as service_module

    async def fake_complete(llm, system, user):
        return (
            '[{"fact":"MORICE has five years of backend experience",'
            '"category":"professional",'
            '"quote":"five years of backend engineering experience"}]'
        )

    monkeypatch.setattr(service_module, "_complete", fake_complete)

    fact = client.post(f"/documents/{document['id']}/extract-facts").json()[0]
    assert fact["status"] == "proposed"

    # Not yet a fact-kind memory.
    facts_in_memory = [i for i in client.get("/memory").json() if i["kind"] == "fact"]
    assert facts_in_memory == []

    accepted = client.post(
        f"/documents/facts/{fact['id']}/decide", json={"accept": True}
    ).json()
    assert accepted["status"] == "accepted"

    facts_in_memory = [i for i in client.get("/memory").json() if i["kind"] == "fact"]
    assert len(facts_in_memory) == 1
    assert "you accepted this from 'cv.txt'" in facts_in_memory[0]["provenance"]


def test_a_rejected_fact_never_reaches_memory(client: TestClient, monkeypatch) -> None:
    document = _upload(client, "cv.txt", b"MORICE enjoys long distance running.").json()

    from src.documents import service as service_module

    async def fake_complete(llm, system, user):
        return (
            '[{"fact":"MORICE is a runner","category":"personal",'
            '"quote":"enjoys long distance running"}]'
        )

    monkeypatch.setattr(service_module, "_complete", fake_complete)
    fact = client.post(f"/documents/{document['id']}/extract-facts").json()[0]

    client.post(f"/documents/facts/{fact['id']}/decide", json={"accept": False})
    assert [i for i in client.get("/memory").json() if i["kind"] == "fact"] == []


def test_deciding_a_fact_twice_is_refused(client: TestClient, monkeypatch) -> None:
    document = _upload(client, "cv.txt", b"MORICE studied computer science.").json()

    from src.documents import service as service_module

    async def fake_complete(llm, system, user):
        return (
            '[{"fact":"He studied CS","category":"personal",'
            '"quote":"MORICE studied computer science"}]'
        )

    monkeypatch.setattr(service_module, "_complete", fake_complete)
    fact = client.post(f"/documents/{document['id']}/extract-facts").json()[0]

    client.post(f"/documents/facts/{fact['id']}/decide", json={"accept": False})
    again = client.post(f"/documents/facts/{fact['id']}/decide", json={"accept": True})
    assert again.status_code == 409


# ---------- asking ----------

def test_asking_is_scoped_to_one_document(client: TestClient) -> None:
    """'What does my contract say' must not be answered from a different one."""
    contract = _upload(
        client, "contract.txt", b"The notice period is thirty days."
    ).json()
    _upload(client, "other.txt", b"The notice period is ninety days.")

    answer = client.post(
        f"/documents/{contract['id']}/ask", json={"question": "What is the notice period?"}
    ).json()
    assert answer["document"] == "contract.txt"
    assert answer["scope"] == "this document only"
    # The fake LLM echoes its prompt, so the scoped document is what it saw.
    assert "thirty days" in answer["answer"]
    assert "ninety days" not in answer["answer"]


def test_asking_about_a_missing_document_is_404(client: TestClient) -> None:
    assert (
        client.post("/documents/nope/ask", json={"question": "hi"}).status_code == 404
    )
