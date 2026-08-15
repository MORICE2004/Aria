"""LLM provider package.

Two ways to get a model, both vendor-agnostic:

  get_llm_provider()      — the configured default provider (legacy path,
                            used by routers that don't care about task class).
  get_router().resolve(t) — task-aware routing: local for routine work,
                            cloud for reasoning, with automatic fallback.

Adding a vendor is still one adapter file plus a branch in
`build_cloud_provider`. Nothing else in the codebase imports a vendor SDK.
"""

from functools import lru_cache

from fastapi import HTTPException

from src.core.config import get_settings
from src.llm.base import LLMProvider


def build_cloud_provider() -> tuple[LLMProvider, str] | None:
    """Construct the configured cloud provider, or None if no key is set.

    Returns (provider, model_name). Never raises for a missing key — the
    router treats "not configured" as "try the next tier".
    """
    settings = get_settings()

    if settings.llm_provider == "openai" and settings.openai_api_key:
        from src.llm.openai import OpenAIProvider

        return (
            OpenAIProvider(
                api_key=settings.openai_api_key, model=settings.openai_model
            ),
            settings.openai_model,
        )

    if settings.llm_provider == "gemini" and settings.gemini_api_key:
        from src.llm.gemini import GeminiProvider

        return (
            GeminiProvider(
                api_key=settings.gemini_api_key, model=settings.gemini_model
            ),
            settings.gemini_model,
        )

    if settings.llm_provider == "claude" and settings.anthropic_api_key:
        from src.llm.claude import ClaudeProvider, MODEL

        return ClaudeProvider(api_key=settings.anthropic_api_key), MODEL

    return None


@lru_cache
def _cached_provider() -> LLMProvider:
    """The configured default provider, or a clear error explaining the fix."""
    settings = get_settings()
    known = {"claude", "openai", "gemini"}
    if settings.llm_provider not in known:
        raise ValueError(
            f"Unknown LLM_PROVIDER {settings.llm_provider!r} — "
            f"use one of {sorted(known)}."
        )

    built = build_cloud_provider()
    if built is not None:
        return built[0]

    # No cloud key: fall back to a local model rather than failing outright.
    if settings.ollama_fast_model:
        from src.llm.ollama import OllamaProvider

        return OllamaProvider(
            base_url=settings.ollama_base_url, model=settings.ollama_fast_model
        )

    key_name = {
        "claude": "ANTHROPIC_API_KEY",
        "openai": "OPENAI_API_KEY",
        "gemini": "GEMINI_API_KEY",
    }[settings.llm_provider]
    raise ValueError(
        f"{key_name} is not set, and no local Ollama model is configured. "
        "Add the key to .env, or pull a local model "
        "(`ollama pull llama3.2:3b`) and set OLLAMA_FAST_MODEL."
    )


def get_llm_provider() -> LLMProvider:
    """FastAPI dependency returning the default provider.

    Tests override this with a fake provider, so the suite never calls
    (or pays for) a real API.
    """
    try:
        return _cached_provider()
    except ValueError as exc:
        # 503 = "service not ready" — the honest status for missing config.
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@lru_cache
def get_router():
    """FastAPI dependency returning the task-aware model router."""
    from src.llm.router import ModelRouter

    return ModelRouter()
