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


# ---------- reachability from a phone ----------

def test_cors_allows_home_wifi_and_tailscale_but_not_the_internet() -> None:
    """The regex is the whole access policy for a phone.

    Tailscale needs its own entry because 100.64.0.0/10 is the carrier-grade
    NAT block, NOT one of the RFC1918 private ranges - so a policy that only
    lists private ranges silently blocks the tunnel, and it looks like ARIA is
    broken rather than like a policy decision.
    """
    import re

    from src.main import create_app

    app = create_app()
    pattern = next(
        m.kwargs["allow_origin_regex"]
        for m in app.user_middleware
        if "allow_origin_regex" in getattr(m, "kwargs", {})
    )
    allowed = re.compile(pattern)

    for origin in (
        "http://192.168.10.247:3000",   # home Wi-Fi
        "http://10.0.0.5:3000",
        "http://100.64.0.1:3000",       # Tailscale, low end of the range
        "http://100.127.255.254:3000",  # Tailscale, high end
        "http://100.101.102.103:3000",
        "https://laptop.tail1234.ts.net",  # MagicDNS
    ):
        assert allowed.match(origin), f"should be reachable: {origin}"

    for origin in (
        "http://evil.com",
        "https://aria.example.com",
        "http://100.63.0.1:3000",   # just below the Tailscale range
        "http://100.128.0.1:3000",  # just above it
        "http://8.8.8.8:3000",
    ):
        assert not allowed.match(origin), f"must NOT be reachable: {origin}"


def test_connect_reports_tailscale_when_present(client: TestClient, monkeypatch) -> None:
    """The Tailscale address is the one that works away from home, so it is
    worth showing even when a LAN address also exists."""
    from src.routers import connect as connect_module

    monkeypatch.setattr(connect_module, "detect_tailscale_ip", lambda: "100.101.102.103")
    monkeypatch.setattr(connect_module, "detect_lan_ip", lambda: "192.168.10.247")

    body = client.get("/connect").json()
    assert body["tailscale_url"] == "http://100.101.102.103:3000"
    assert body["phone_url"] == "http://192.168.10.247:3000"


def test_connect_still_works_with_no_tailscale(client: TestClient, monkeypatch) -> None:
    from src.routers import connect as connect_module

    monkeypatch.setattr(connect_module, "detect_tailscale_ip", lambda: None)
    monkeypatch.setattr(connect_module, "detect_lan_ip", lambda: "192.168.10.247")

    body = client.get("/connect").json()
    assert body["tailscale_url"] is None
    assert body["phone_url"] == "http://192.168.10.247:3000"
