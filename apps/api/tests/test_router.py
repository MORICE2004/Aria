"""Tests for the model router.

The router's job is choosing WHERE work runs. These tests pin the routing
policy and — most importantly — the fallback behaviour, since a wrong
fallback silently sends private data to a cloud provider or silently
degrades quality.
"""

import pytest

from src.core.config import get_settings
from src.llm.router import ModelRouter, TaskClass, Tier


@pytest.fixture
def settings_reset():
    """Snapshot and restore settings mutated by a test."""
    s = get_settings()
    before = (
        s.llm_provider, s.gemini_api_key, s.openai_api_key, s.anthropic_api_key,
        s.ollama_fast_model, s.ollama_reasoning_model, s.prefer_local,
    )
    yield s
    (
        s.llm_provider, s.gemini_api_key, s.openai_api_key, s.anthropic_api_key,
        s.ollama_fast_model, s.ollama_reasoning_model, s.prefer_local,
    ) = before


def test_routine_work_prefers_local(settings_reset) -> None:
    s = settings_reset
    s.ollama_fast_model = "llama3.2:3b"
    s.llm_provider, s.gemini_api_key = "gemini", "fake-key"

    routed = ModelRouter().resolve(TaskClass.ROUTINE)
    assert routed.tier is Tier.LOCAL_FAST
    assert routed.model == "llama3.2:3b"
    assert "locally" in routed.description


def test_reasoning_prefers_cloud(settings_reset) -> None:
    s = settings_reset
    s.ollama_fast_model = "llama3.2:3b"
    s.llm_provider, s.gemini_api_key = "gemini", "fake-key"

    routed = ModelRouter().resolve(TaskClass.REASON)
    assert routed.tier is Tier.CLOUD
    assert "cloud" in routed.description


def test_prefer_local_overrides_cloud_for_reasoning(settings_reset) -> None:
    """The privacy/cost escape hatch: keep everything local on request."""
    s = settings_reset
    s.ollama_fast_model = "llama3.2:3b"
    s.llm_provider, s.gemini_api_key = "gemini", "fake-key"
    s.prefer_local = True

    assert ModelRouter().resolve(TaskClass.REASON).tier is not Tier.CLOUD


def test_falls_back_to_cloud_when_no_local_model(settings_reset) -> None:
    s = settings_reset
    s.ollama_fast_model = ""
    s.ollama_reasoning_model = ""
    s.llm_provider, s.gemini_api_key = "gemini", "fake-key"

    assert ModelRouter().resolve(TaskClass.ROUTINE).tier is Tier.CLOUD


def test_falls_back_to_local_when_no_cloud_key(settings_reset) -> None:
    """No API key must not break ARIA — local picks up the work."""
    s = settings_reset
    s.ollama_fast_model = "llama3.2:3b"
    s.llm_provider = "gemini"
    s.gemini_api_key = s.openai_api_key = s.anthropic_api_key = ""

    assert ModelRouter().resolve(TaskClass.REASON).tier is Tier.LOCAL_FAST


def test_no_provider_at_all_raises_actionable_error(settings_reset) -> None:
    s = settings_reset
    s.ollama_fast_model = s.ollama_reasoning_model = ""
    s.gemini_api_key = s.openai_api_key = s.anthropic_api_key = ""

    with pytest.raises(RuntimeError, match="ollama pull|LLM_PROVIDER"):
        ModelRouter().resolve(TaskClass.CONVERSE)
