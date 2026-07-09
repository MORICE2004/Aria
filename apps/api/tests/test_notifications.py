"""Tests for the notifications aggregator and the read-only inbox."""

from fastapi.testclient import TestClient


def test_inbox_unconfigured_gives_clear_503(client: TestClient) -> None:
    response = client.get("/communication/inbox")
    assert response.status_code == 503
    assert "IMAP is not configured" in response.json()["detail"]


def test_notifications_aggregate(client: TestClient) -> None:
    # One pending approval + one overdue task + one due-far-future task.
    client.post("/actions/demo", json={"message": "needs review"})
    client.post("/tasks", json={"title": "Overdue thing", "due_at": "2020-01-01T09:00:00Z"})
    client.post("/tasks", json={"title": "Far future", "due_at": "2099-01-01T09:00:00Z"})

    body = client.get("/notifications").json()
    assert body["pending_approvals"] == 1
    assert [t["title"] for t in body["due_tasks"]] == ["Overdue thing"]
    assert body["due_tasks"][0]["overdue"] is True
    # IMAP unconfigured: email section is null with the reason, not an error.
    assert body["unread_emails"] is None
    assert "IMAP is not configured" in body["email_error"]


def test_notifications_done_tasks_excluded(client: TestClient) -> None:
    task = client.post(
        "/tasks", json={"title": "Done already", "due_at": "2020-01-01T09:00:00Z"}
    ).json()
    client.patch(f"/tasks/{task['id']}", json={"status": "done"})
    assert client.get("/notifications").json()["due_tasks"] == []
