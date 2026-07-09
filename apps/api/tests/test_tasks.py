"""Tests for tasks, reminders, and deadlines."""

from fastapi.testclient import TestClient


def test_task_lifecycle(client: TestClient) -> None:
    created = client.post(
        "/tasks",
        json={"title": "Prepare for Acme interview", "kind": "interview",
              "due_at": "2026-07-15T14:00:00Z"},
    )
    assert created.status_code == 201
    task = created.json()
    assert task["status"] == "open"

    done = client.patch(f"/tasks/{task['id']}", json={"status": "done"}).json()
    assert done["status"] == "done"

    assert client.delete(f"/tasks/{task['id']}").status_code == 204
    assert client.get("/tasks").json() == []


def test_urgency_ordering(client: TestClient) -> None:
    client.post("/tasks", json={"title": "no date"})
    client.post("/tasks", json={"title": "later", "due_at": "2026-08-01T09:00:00Z"})
    client.post("/tasks", json={"title": "soon", "due_at": "2026-07-10T09:00:00Z"})
    titles = [t["title"] for t in client.get("/tasks").json()]
    assert titles == ["soon", "later", "no date"]


def test_status_filter(client: TestClient) -> None:
    a = client.post("/tasks", json={"title": "open one"}).json()
    b = client.post("/tasks", json={"title": "done one"}).json()
    client.patch(f"/tasks/{b['id']}", json={"status": "done"})
    open_titles = [t["title"] for t in client.get("/tasks", params={"status": "open"}).json()]
    assert open_titles == ["open one"] and a["id"]


def test_validation(client: TestClient) -> None:
    assert client.post("/tasks", json={"title": "x", "kind": "party"}).status_code == 422
    assert client.post("/tasks", json={"title": ""}).status_code == 422
    task = client.post("/tasks", json={"title": "ok"}).json()
    assert client.patch(f"/tasks/{task['id']}", json={"status": "paused"}).status_code == 422
    assert client.patch("/tasks/nope", json={"status": "done"}).status_code == 404
