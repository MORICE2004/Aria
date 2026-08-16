"""Security hardening tests.

Three properties, each of which was false before this change:

  1. ARIA will not send messages unattended when she has no password.
     Autonomy plus no access control means anyone who can reach her — and she
     listens on the LAN so the phone can use her — can send WhatsApp messages
     as MORICE.

  2. Login resists guessing: rate limited, progressively locked out, and
     indistinguishable in its error messages.

  3. ARIA refuses to boot with security that only looks real. Running without
     auth is a choice, logged loudly. Running WITH auth that anyone can forge
     is a lie, and she will not tell it.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from src.core import ratelimit
from src.core.security import (
    DEFAULT_SECRET_KEY,
    InsecureConfiguration,
    check_startup_security,
)
from src.whatsapp.decision import Decision, Mode, TrustLevel, decide
from src.whatsapp.risk import RiskAssessment, RiskLevel


# ---------- 1. autonomy requires access control ----------

def _autonomy_ready_signals(**overrides):
    from src.whatsapp.decision import Signals

    base = dict(
        contact_name="John",
        relationship="friend",
        trust=TrustLevel.HIGH,
        global_mode=Mode.LIMITED_AUTONOMY,
        effective_mode=Mode.LIMITED_AUTONOMY,
        action="greeting",
        risk=RiskAssessment(level=RiskLevel.LOW, reasons=["routine"]),
        communication_confidence=0.85,
        correction_rate=0.0,
        autonomous_responses=10,
        contact_autonomy_enabled=True,
        allowed_actions=("greeting",),
        forbidden_actions=(),
        emergency_stop=False,
        paused=False,
        autonomy_stopped=False,
        contact_paused=False,
        taken_over=False,
        auth_enabled=True,
    )
    base.update(overrides)
    return Signals(**base)


def test_autonomy_is_refused_when_aria_has_no_password() -> None:
    """The whole point: an unprotected ARIA must not act on her own."""
    outcome = decide(_autonomy_ready_signals(auth_enabled=False))
    assert outcome.decision is Decision.ASK_USER
    assert "no password" in outcome.reasons[0]


def test_the_same_situation_auto_sends_once_a_password_exists() -> None:
    """Proves the refusal above is caused by auth and nothing else."""
    assert decide(_autonomy_ready_signals()).decision is Decision.AUTO_SEND


def test_drafting_still_works_without_auth(client: TestClient) -> None:
    """Suggesting is a tolerable risk without a login; sending is not.

    Disabling drafting too would make an unprotected ARIA useless rather than
    safe, and MORICE would just turn the check off.
    """
    contact = client.post(
        "/whatsapp/contacts",
        json={"name": "Ann", "handle": "ann@s.whatsapp.net", "relationship": "friend"},
    ).json()
    client.patch(f"/whatsapp/contacts/{contact['id']}", json={"trust_level": "trusted"})
    client.patch("/whatsapp/autonomy", json={"mode": "suggest"})

    observation = client.post(
        "/whatsapp/simulate",
        json={"handle": "ann@s.whatsapp.net", "name": "Ann", "body": "you free?"},
    ).json()
    assert observation["draft"] is not None
    assert client.get("/whatsapp/outbound").json() == []


def test_live_evaluate_reports_the_auth_refusal(client: TestClient) -> None:
    """MORICE must be told WHY she will not act, not just that she will not."""
    contact = client.post(
        "/whatsapp/contacts",
        json={"name": "John", "handle": "john@s.whatsapp.net", "relationship": "friend"},
    ).json()
    client.patch(f"/whatsapp/contacts/{contact['id']}", json={"trust_level": "high"})
    client.patch(
        f"/whatsapp/contacts/{contact['id']}",
        json={"autonomy_enabled": True, "allowed_actions": ["greeting"]},
    )
    client.patch("/whatsapp/autonomy", json={"mode": "limited_autonomy"})

    result = client.post(
        "/whatsapp/evaluate", json={"handle": "john@s.whatsapp.net", "body": "hey"}
    ).json()
    assert result["decision"] != "auto_send"
    assert any("password" in r or "confidence" in r for r in result["reasons"])


# ---------- 2. login resists guessing ----------

def test_wrong_password_is_rejected_with_a_vague_message(
    client: TestClient, auth_enabled
) -> None:
    response = client.post("/auth/login", json={"password": "wrong"})
    assert response.status_code == 401
    # No hint about whether the password was close, or whether auth is on.
    assert response.json()["detail"] == "Login failed"


def test_repeated_failures_trigger_a_lockout(
    client: TestClient, auth_enabled
) -> None:
    for _ in range(ratelimit.login_lockout.threshold):
        client.post("/auth/login", json={"password": "wrong"})

    blocked = client.post("/auth/login", json={"password": "wrong"})
    assert blocked.status_code == 429
    assert "Retry-After" in blocked.headers

    # And the lockout applies even to the CORRECT password, so an attacker
    # cannot use timing differences to confirm a guess mid-lockout.
    correct = client.post(
        "/auth/login", json={"password": "test-password-long-enough"}
    )
    assert correct.status_code == 429


def test_a_correct_password_clears_the_failure_record(
    client: TestClient, auth_enabled
) -> None:
    """MORICE mistyping his password twice must not punish him later."""
    for _ in range(2):
        client.post("/auth/login", json={"password": "wrong"})

    good = client.post("/auth/login", json={"password": "test-password-long-enough"})
    assert good.status_code == 200
    assert good.json()["token"]

    # Record cleared: the earlier failures no longer count toward a lockout.
    for _ in range(ratelimit.login_lockout.threshold - 1):
        assert client.post("/auth/login", json={"password": "wrong"}).status_code == 401


def test_lockout_grows_with_repeated_offences() -> None:
    """A fixed penalty just teaches an attacker how long to wait."""
    lockout = ratelimit.Lockout(threshold=2, base_seconds=10)
    lockout.record_failure("attacker")
    first = lockout.record_failure("attacker")
    second = lockout.record_failure("attacker")
    assert second > first > 0


def test_rate_limiter_uses_a_sliding_window() -> None:
    """A fixed window would allow a double burst across the boundary."""
    limiter = ratelimit.RateLimiter(limit=2, window_seconds=60)
    assert limiter.check("a")[0] is True
    assert limiter.check("a")[0] is True
    allowed, retry_after = limiter.check("a")
    assert allowed is False
    assert retry_after > 0
    # Limits are per caller, not global.
    assert limiter.check("b")[0] is True


def test_forwarded_headers_cannot_reset_a_rate_limit(client: TestClient) -> None:
    """X-Forwarded-For is attacker-controlled, so it must not key the limiter."""
    from types import SimpleNamespace

    request = SimpleNamespace(
        client=SimpleNamespace(host="10.0.0.5"),
        headers={"X-Forwarded-For": "1.2.3.4"},
    )
    assert ratelimit.client_key(request) == "10.0.0.5"


def test_general_api_traffic_is_rate_limited(client: TestClient) -> None:
    limiter = ratelimit.api_limiter
    original = limiter.limit
    limiter.limit = 3
    try:
        for _ in range(3):
            client.get("/whatsapp/autonomy")
        assert client.get("/whatsapp/autonomy").status_code == 429
    finally:
        limiter.limit = original


def test_health_is_never_rate_limited(client: TestClient) -> None:
    """A monitoring endpoint that can be rate limited is a monitoring endpoint
    that goes dark exactly when something is wrong."""
    limiter = ratelimit.api_limiter
    original = limiter.limit
    limiter.limit = 1
    try:
        client.get("/whatsapp/autonomy")
        for _ in range(5):
            assert client.get("/health").status_code == 200
    finally:
        limiter.limit = original


def test_ingest_has_its_own_budget_for_backlog_bursts(
    client: TestClient, ingest_secret
) -> None:
    """After an outage the bridge delivers a whole spool at once.

    That burst must not be mistaken for abuse, or recovery would rate-limit
    itself into failure.
    """
    api_limit = ratelimit.api_limiter.limit
    ratelimit.api_limiter.limit = 1
    try:
        client.get("/whatsapp/autonomy")  # exhaust the general budget
        for index in range(20):
            response = client.post(
                "/whatsapp/ingest",
                json={
                    "handle": "friend@s.whatsapp.net",
                    "body": f"backlog {index}",
                    "message_id": f"burst.{index}",
                },
                headers={"X-ARIA-Ingest-Secret": ingest_secret},
            )
            assert response.status_code == 202, f"message {index} was rejected"
    finally:
        ratelimit.api_limiter.limit = api_limit


# ---------- 3. refuse security theatre ----------

def test_startup_warns_loudly_when_auth_is_disabled() -> None:
    from src.core.config import get_settings

    settings = get_settings()
    before = settings.aria_password
    settings.aria_password = ""
    try:
        warnings = check_startup_security()
        assert any("AUTH IS DISABLED" in w for w in warnings)
    finally:
        settings.aria_password = before


def test_startup_refuses_auth_with_the_example_secret_key() -> None:
    """Auth signed with a published key is worse than no auth: it looks safe."""
    from src.core.config import get_settings

    settings = get_settings()
    before = (settings.aria_password, settings.secret_key)
    settings.aria_password = "a-real-password"
    settings.secret_key = DEFAULT_SECRET_KEY
    try:
        with pytest.raises(InsecureConfiguration, match="example value"):
            check_startup_security()
    finally:
        settings.aria_password, settings.secret_key = before


def test_startup_refuses_a_short_secret_key() -> None:
    from src.core.config import get_settings

    settings = get_settings()
    before = (settings.aria_password, settings.secret_key)
    settings.aria_password = "a-real-password"
    settings.secret_key = "too-short"
    try:
        with pytest.raises(InsecureConfiguration, match="characters"):
            check_startup_security()
    finally:
        settings.aria_password, settings.secret_key = before


def test_startup_accepts_a_properly_configured_system() -> None:
    from src.core.config import get_settings

    settings = get_settings()
    before = (settings.aria_password, settings.secret_key)
    settings.aria_password = "a-genuinely-long-password"
    settings.secret_key = "x" * 48
    try:
        assert check_startup_security() == []
    finally:
        settings.aria_password, settings.secret_key = before


def test_auth_status_admits_when_aria_is_unprotected(client: TestClient) -> None:
    status = client.get("/auth/status").json()
    assert status["auth_enabled"] is False
    assert "Auth is disabled" in status["warning"]
