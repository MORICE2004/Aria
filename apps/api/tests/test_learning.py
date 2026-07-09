"""Tests for the learning coach: topic tracker and tutor tools."""

from fastapi.testclient import TestClient


def test_topic_lifecycle(client: TestClient) -> None:
    created = client.post("/learning/topics", json={"name": "Python functions"})
    assert created.status_code == 201
    topic = created.json()
    assert topic["status"] == "learning"

    updated = client.patch(
        f"/learning/topics/{topic['id']}", json={"status": "comfortable"}
    ).json()
    assert updated["status"] == "comfortable"

    assert client.patch(
        f"/learning/topics/{topic['id']}", json={"status": "genius"}
    ).status_code == 422

    assert client.delete(f"/learning/topics/{topic['id']}").status_code == 204
    assert client.get("/learning/topics").json() == []


def test_explain_includes_progress(client: TestClient) -> None:
    client.post("/learning/topics", json={"name": "Variables"})
    response = client.post("/learning/explain", json={"concept": "for loops"})
    assert response.status_code == 200
    # FakeLLM echoes the prompt we built — proves the progress list is included.
    text = response.json()["text"]
    assert "Variables" in text and "for loops" in text


def test_review_marks_code_as_data(client: TestClient) -> None:
    response = client.post(
        "/learning/review", json={"code": "print('hi')", "question": "is this ok?"}
    )
    assert response.status_code == 200
    assert "CODE START" in response.json()["text"]


def test_path_requires_goal(client: TestClient) -> None:
    assert client.post("/learning/path", json={"goal": ""}).status_code == 422
    response = client.post("/learning/path", json={"goal": "backend developer"})
    assert response.status_code == 200 and response.json()["text"]
