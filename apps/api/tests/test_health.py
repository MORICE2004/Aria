"""Tests for the health endpoint.

Uses FastAPI's TestClient: it calls the app in-process, so no server or
database needs to be running for the test suite to pass.
"""

from fastapi.testclient import TestClient

from src.main import create_app

client = TestClient(create_app())


def test_health_returns_ok() -> None:
    response = client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["version"] == "0.2.0"


def test_unknown_route_returns_404() -> None:
    response = client.get("/does-not-exist")
    assert response.status_code == 404
