"""Tests for the Action Gateway — the safety-critical component.

These tests pin down the guarantees, not implementation details:
  * nothing executes while pending
  * approve runs the action exactly once
  * reject never executes
  * decided requests cannot be re-decided
  * every step leaves an audit event
"""

from fastapi.testclient import TestClient


def _submit(client: TestClient, message: str = "hello") -> dict:
    response = client.post("/actions/demo", json={"message": message})
    assert response.status_code == 201
    return response.json()


def test_submitted_action_is_pending_and_unexecuted(client: TestClient) -> None:
    action = _submit(client)
    assert action["status"] == "pending"
    assert action["result"] == ""


def test_approve_executes_exactly_the_requested_payload(client: TestClient) -> None:
    action = _submit(client, "send this")
    approved = client.post(f"/actions/{action['id']}/approve").json()
    assert approved["status"] == "executed"
    assert "'send this'" in approved["result"]


def test_reject_never_executes(client: TestClient) -> None:
    action = _submit(client)
    rejected = client.post(
        f"/actions/{action['id']}/reject", json={"reason": "changed my mind"}
    ).json()
    assert rejected["status"] == "rejected"
    assert rejected["result"] == ""


def test_decided_actions_cannot_be_redecided(client: TestClient) -> None:
    action = _submit(client)
    client.post(f"/actions/{action['id']}/approve")
    # A second approval (double-send!) and a late rejection must both fail.
    assert client.post(f"/actions/{action['id']}/approve").status_code == 409
    assert client.post(f"/actions/{action['id']}/reject", json={}).status_code == 409


def test_full_audit_trail_is_recorded(client: TestClient) -> None:
    action = _submit(client)
    client.post(f"/actions/{action['id']}/approve")
    events = [e["event"] for e in client.get(f"/actions/{action['id']}/audit").json()]
    assert events == ["submitted", "approved", "executed"]


def test_status_filter(client: TestClient) -> None:
    kept = _submit(client, "keep me")
    done = _submit(client, "approve me")
    client.post(f"/actions/{done['id']}/approve")
    pending = client.get("/actions", params={"status": "pending"}).json()
    assert [a["id"] for a in pending] == [kept["id"]]


def test_agents_are_listed(client: TestClient) -> None:
    agents = client.get("/agents").json()
    assert any(a["name"] == "demo" for a in agents)
