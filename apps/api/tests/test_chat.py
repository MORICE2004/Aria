"""Tests for the chat endpoints (fake LLM, in-memory SQLite — see conftest.py)."""

from fastapi.testclient import TestClient


def _create_conversation(client: TestClient) -> str:
    response = client.post("/conversations")
    assert response.status_code == 201
    return response.json()["id"]


def test_create_and_list_conversations(client: TestClient) -> None:
    conversation_id = _create_conversation(client)
    listed = client.get("/conversations").json()
    assert [c["id"] for c in listed] == [conversation_id]


def test_send_message_streams_reply_and_persists_history(client: TestClient) -> None:
    conversation_id = _create_conversation(client)

    response = client.post(
        f"/conversations/{conversation_id}/messages",
        json={"content": "Hello ARIA"},
    )
    assert response.status_code == 200
    assert response.text == "Echo: Hello ARIA"  # FakeLLM's reply

    # Both the user message and the assistant reply must be saved, in order.
    messages = client.get(f"/conversations/{conversation_id}/messages").json()
    assert [(m["role"], m["content"]) for m in messages] == [
        ("user", "Hello ARIA"),
        ("assistant", "Echo: Hello ARIA"),
    ]

    # The conversation title picks up the first message.
    assert client.get("/conversations").json()[0]["title"] == "Hello ARIA"


def test_llm_receives_full_history(client: TestClient) -> None:
    conversation_id = _create_conversation(client)
    client.post(f"/conversations/{conversation_id}/messages", json={"content": "one"})
    client.post(f"/conversations/{conversation_id}/messages", json={"content": "two"})

    messages = client.get(f"/conversations/{conversation_id}/messages").json()
    assert len(messages) == 4  # two user turns + two assistant replies


def test_empty_message_rejected(client: TestClient) -> None:
    conversation_id = _create_conversation(client)
    response = client.post(
        f"/conversations/{conversation_id}/messages", json={"content": ""}
    )
    assert response.status_code == 422  # validation error at the boundary


def test_unknown_conversation_404(client: TestClient) -> None:
    response = client.get("/conversations/nope/messages")
    assert response.status_code == 404


def test_delete_conversation(client: TestClient) -> None:
    conversation_id = _create_conversation(client)
    assert client.delete(f"/conversations/{conversation_id}").status_code == 204
    assert client.get("/conversations").json() == []
