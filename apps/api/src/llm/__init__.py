"""LLM provider package.

The rest of the codebase imports `get_llm_provider` from here and never
touches a vendor SDK directly. Swapping Claude for OpenAI or a local model
means adding one adapter file and changing this factory — nothing else.
"""

from functools import lru_cache

from fastapi import HTTPException

from src.core.config import get_settings
from src.llm.base import LLMProvider
from src.llm.claude import ClaudeProvider


@lru_cache
def _cached_provider() -> LLMProvider:
    return ClaudeProvider(api_key=get_settings().anthropic_api_key)


def get_llm_provider() -> LLMProvider:
    """FastAPI dependency returning the configured LLM provider.

    Tests override this dependency with a fake provider, so the test suite
    never calls (or pays for) a real API.
    """
    try:
        return _cached_provider()
    except ValueError as exc:
        # Missing API key: tell the user exactly what to fix (503 = "service
        # not ready", the honest status here) instead of a vague 500.
        raise HTTPException(status_code=503, detail=str(exc)) from exc
