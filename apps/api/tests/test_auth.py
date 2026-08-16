"""Tests for authentication.

The suite runs with auth DISABLED (no ARIA_PASSWORD) except where a test
enables it by mutating the cached settings object.
"""

import pytest
from fastapi.testclient import TestClient

from src.core.config import get_settings


@pytest.fixture
def with_password():
    """Temporarily enable auth for one test."""
    settings = get_settings()
    settings.aria_password = "correct-horse"
    yield
    settings.aria_password = ""


def test_auth_disabled_allows_requests(client: TestClient) -> None:
    assert client.get("/conversations").status_code == 200
    status = client.get("/auth/status").json()
    assert status["auth_enabled"] is False
    # An unprotected ARIA must not look identical to a protected one.
    assert "Auth is disabled" in status["warning"]


def test_protected_routes_require_token(client: TestClient, with_password) -> None:
    assert client.get("/conversations").status_code == 401
    assert client.get("/memory").status_code == 401
    assert client.get("/actions").status_code == 401
    # Health stays public for monitoring.
    assert client.get("/health").status_code == 200


def test_wrong_password_rejected(client: TestClient, with_password) -> None:
    assert client.post("/auth/login", json={"password": "guess"}).status_code == 401


def test_login_token_grants_access(client: TestClient, with_password) -> None:
    token = client.post(
        "/auth/login", json={"password": "correct-horse"}
    ).json()["token"]
    response = client.get(
        "/conversations", headers={"Authorization": f"Bearer {token}"}
    )
    assert response.status_code == 200


def test_garbage_token_rejected(client: TestClient, with_password) -> None:
    response = client.get(
        "/conversations", headers={"Authorization": "Bearer not.a.token"}
    )
    assert response.status_code == 401
