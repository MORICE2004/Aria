"""Tests for the health and readiness endpoints.

The distinction under test: liveness must never fail because a dependency is
down. Conflating the two gets a healthy API restarted because Ollama is
unavailable, which fixes nothing and loses the queue worker's in-flight state.
"""

from fastapi.testclient import TestClient

from src.main import create_app
from src.routers.health import VERSION

client = TestClient(create_app())


def test_health_returns_ok() -> None:
    response = client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["version"] == VERSION


def test_health_does_not_depend_on_anything(monkeypatch) -> None:
    """Liveness must stay green when every dependency is down."""
    from src.routers import health as health_module

    async def dead(*args, **kwargs):
        raise RuntimeError("everything is on fire")

    monkeypatch.setattr(health_module, "_check_database", dead)
    monkeypatch.setattr(health_module, "_check_ollama", dead)

    assert client.get("/health").status_code == 200


def test_ready_reports_each_dependency_separately(client: TestClient) -> None:
    """Every check reports independently.

    'The database is down' and 'the database AND the model are down' are
    different situations; the second must not be hidden by the first.
    """
    body = client.get("/ready").json()
    assert set(body["checks"]) >= {
        "database",
        "schema",
        "local_model",
        "workers",
        "auth",
    }
    for name, check in body["checks"].items():
        assert isinstance(check["ok"], bool), name


def test_ready_surfaces_a_missing_password_without_blocking(
    client: TestClient,
) -> None:
    """Auth off is a posture warning, not an outage."""
    body = client.get("/ready").json()
    assert body["checks"]["auth"]["ok"] is False
    assert "no password set" in body["checks"]["auth"]["detail"]


def test_unknown_route_returns_404() -> None:
    response = client.get("/does-not-exist")
    assert response.status_code == 404
