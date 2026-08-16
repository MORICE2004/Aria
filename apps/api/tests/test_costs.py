"""Tests for usage and cost tracking.

The distinction that matters: token counts are facts, costs are estimates.
Local work must always be recorded at exactly zero.
"""

from fastapi.testclient import TestClient

from src.llm.base import Usage
from src.llm.costs import estimate_cost, price_for


def test_local_calls_are_free() -> None:
    """The one cost figure that is certain."""
    usage = Usage(input_tokens=100_000, output_tokens=100_000)
    assert estimate_cost("llama3.2:3b", usage, is_local=True) == 0.0


def test_unknown_model_is_not_guessed() -> None:
    """A fabricated cost is worse than an absent one."""
    assert price_for("some-model-nobody-has-heard-of") is None
    usage = Usage(input_tokens=1000, output_tokens=1000)
    assert estimate_cost("some-model-nobody-has-heard-of", usage, is_local=False) == 0.0


def test_known_model_is_priced_from_the_table() -> None:
    usage = Usage(input_tokens=1_000_000, output_tokens=1_000_000)
    cost = estimate_cost("gemini-2.5-flash", usage, is_local=False)
    # 1M in + 1M out at the table rate.
    assert cost == round(0.30 + 2.50, 6)


def test_model_id_with_suffix_still_matches() -> None:
    assert price_for("gemini-2.5-flash-preview-0325") is not None


def test_summary_is_empty_and_honest_at_start(client: TestClient) -> None:
    body = client.get("/costs").json()
    assert body["totals"]["all_time"]["calls"] == 0
    assert body["totals"]["all_time"]["estimated_cost_usd"] == 0.0
    assert "estimates" in body["note"]


def test_usage_is_recorded_for_real_calls(client: TestClient) -> None:
    """A chat turn should leave an accounting record."""
    conv = client.post("/conversations").json()
    client.post(f"/conversations/{conv['id']}/messages", json={"content": "hello"})

    body = client.get("/costs").json()
    assert body["totals"]["all_time"]["calls"] >= 1
    assert body["by_model"], "the call should be attributed to a model"
    # The fake router reports the local tier, so it must be free.
    assert body["totals"]["all_time"]["estimated_cost_usd"] == 0.0
    assert body["local_share_pct"] == 100
