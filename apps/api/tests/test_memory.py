"""Tests for memory: chunking, ingest, semantic search, delete."""

from fastapi.testclient import TestClient

from src.memory.chunking import chunk_text


def test_chunking_splits_long_text() -> None:
    text = "\n\n".join(f"Paragraph number {i}. " + "words " * 60 for i in range(6))
    chunks = chunk_text(text, max_chars=800)
    assert len(chunks) > 1
    assert all(len(c) <= 800 + 400 for c in chunks)  # overlap allows slight excess


def test_chunking_empty_text() -> None:
    assert chunk_text("   \n\n  ") == []


def test_add_list_delete_memory(client: TestClient) -> None:
    created = client.post(
        "/memory",
        json={"title": "Career goal", "content": "Become a backend developer.", "kind": "fact"},
    )
    assert created.status_code == 201
    item_id = created.json()["id"]

    assert [m["id"] for m in client.get("/memory").json()] == [item_id]

    assert client.delete(f"/memory/{item_id}").status_code == 204
    assert client.get("/memory").json() == []


def test_invalid_kind_rejected(client: TestClient) -> None:
    response = client.post(
        "/memory", json={"title": "x", "content": "y", "kind": "banana"}
    )
    assert response.status_code == 422


def test_search_finds_relevant_memory(client: TestClient) -> None:
    client.post(
        "/memory",
        json={"title": "Goals", "content": "I want to master python programming", "kind": "fact"},
    )
    client.post(
        "/memory",
        json={"title": "Groceries", "content": "buy milk eggs bread", "kind": "note"},
    )

    hits = client.get("/memory/search", params={"q": "python programming"}).json()
    assert hits[0]["title"] == "Goals"  # most relevant first
    assert hits[0]["score"] > hits[-1]["score"] or len(hits) == 1
