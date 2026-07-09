"""Gemini adapter — the ONLY file that imports Google's GenAI SDK.

Third provider behind the same LLMProvider contract. Notable for MORICE:
Gemini has a free tier (aistudio.google.com — create an API key, no card
needed), so ARIA can run at zero cost, with rate limits.
"""

import logging
from collections.abc import AsyncIterator

from src.llm.base import ChatMessage, LLMProvider

logger = logging.getLogger(__name__)

MAX_TOKENS = 4096


class GeminiProvider(LLMProvider):
    def __init__(self, api_key: str, model: str) -> None:
        if not api_key:
            raise ValueError(
                "GEMINI_API_KEY is not set. Get a free key at aistudio.google.com "
                "and add it to the .env file at the repo root (see .env.example)."
            )
        from google import genai

        self._client = genai.Client(api_key=api_key)
        self._model = model

    async def stream_chat(
        self, messages: list[ChatMessage], system: str
    ) -> AsyncIterator[str]:
        """Stream the reply as text chunks.

        Gemini's role names differ from ours: the assistant is called
        "model". The system prompt goes in config.system_instruction.
        """
        contents = [
            {
                "role": "model" if m.role == "assistant" else "user",
                "parts": [{"text": m.content}],
            }
            for m in messages
        ]
        stream = await self._client.aio.models.generate_content_stream(
            model=self._model,
            contents=contents,
            config={
                "system_instruction": system,
                "max_output_tokens": MAX_TOKENS,
            },
        )
        usage = None
        async for chunk in stream:
            if chunk.text:
                yield chunk.text
            if chunk.usage_metadata:
                usage = chunk.usage_metadata
        if usage:
            logger.info(
                "Gemini call: %s input tokens, %s output tokens",
                usage.prompt_token_count,
                usage.candidates_token_count,
            )
