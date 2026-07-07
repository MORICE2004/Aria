"""Tests for the communication agent and the email approval path."""

from fastapi.testclient import TestClient


def test_draft_returns_text(client: TestClient) -> None:
    response = client.post(
        "/communication/draft",
        json={
            "platform": "whatsapp",
            "conversation": "Friend: are we still on for Saturday?",
            "instructions": "confirm and suggest 3pm",
        },
    )
    assert response.status_code == 200
    # FakeLLM echoes its input — enough to prove the pipeline runs end to end
    # and that the untrusted-data markers are in place.
    assert "CONVERSATION START" in response.json()["text"]


def test_draft_rejects_unknown_platform(client: TestClient) -> None:
    response = client.post(
        "/communication/draft", json={"platform": "carrier-pigeon", "conversation": "x"}
    )
    assert response.status_code == 422


def test_summarize_returns_text(client: TestClient) -> None:
    response = client.post(
        "/communication/summarize", json={"conversation": "A: hi\nB: hello"}
    )
    assert response.status_code == 200
    assert response.json()["text"]


def test_email_request_only_enqueues(client: TestClient) -> None:
    """The critical guarantee: requesting an email sends NOTHING."""
    response = client.post(
        "/communication/email-request",
        json={"to": "friend@example.com", "subject": "Hi", "body": "Hello!"},
    )
    assert response.status_code == 201
    action = response.json()
    assert action["status"] == "pending"
    assert action["action_type"] == "email.send"


def test_email_bad_address_rejected(client: TestClient) -> None:
    response = client.post(
        "/communication/email-request",
        json={"to": "not-an-email", "subject": "Hi", "body": "x"},
    )
    assert response.status_code == 422


def test_approved_email_without_smtp_fails_loudly_and_is_audited(
    client: TestClient,
) -> None:
    """With SMTP unconfigured, approval must record a FAILED outcome (never
    a silent success), and the audit trail must show it."""
    action = client.post(
        "/communication/email-request",
        json={"to": "friend@example.com", "subject": "Hi", "body": "Hello!"},
    ).json()
    approved = client.post(f"/actions/{action['id']}/approve").json()
    assert approved["status"] == "failed"
    assert "SMTP is not configured" in approved["result"]
    events = [e["event"] for e in client.get(f"/actions/{action['id']}/audit").json()]
    assert events == ["submitted", "approved", "failed"]
