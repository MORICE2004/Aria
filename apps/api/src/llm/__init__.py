"""LLM provider package.

One way to get a model, and it is vendor-agnostic:

    routed = get_router().resolve(TaskClass.ROUTINE)
    async for chunk in routed.provider.stream_chat(messages, system=...): ...

Callers declare WHAT KIND of work they need (see src/llm/router.py); the
router decides whether that runs locally or in the cloud, and falls back
automatically when a tier is unavailable.

Adding a vendor is one adapter file plus a branch in `build_cloud_provider`.
Nothing outside this package imports a vendor SDK.
"""

from functools import lru_cache

from src.core.config import get_settings
from src.llm.base import LLMProvider


def build_cloud_provider() -> tuple[LLMProvider, str] | None:
    """Construct the configured cloud provider, or None if no key is set.

    Returns (provider, model_name). Never raises for a missing key — the
    router treats "not configured" as "try the next tier", which is what
    keeps ARIA working when an API key lapses.
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
        from src.llm.claude import MODEL, ClaudeProvider

        return ClaudeProvider(api_key=settings.anthropic_api_key), MODEL

    return None


@lru_cache
def get_router():
    """FastAPI dependency returning the task-aware model router.

    Tests override this with a fake router, so the suite never calls
    (or pays for) a real model.
    """
    from src.llm.router import ModelRouter

    return ModelRouter()
