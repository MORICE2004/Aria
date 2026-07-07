"""OpenAI adapter — the ONLY file that imports the OpenAI SDK.

Same contract as the Claude adapter: this is the whole point of the
LLMProvider abstraction — a new vendor is one file and a config switch.
"""

import logging
from collections.abc import AsyncIterator

from src.llm.base import ChatMessage, LLMProvider

logger = logging.getLogger(__name__)

MAX_TOKENS = 4096


class OpenAIProvider(LLMProvider):
    def __init__(self, api_key: str, model: str) -> None:
        if not api_key:
            raise ValueError(
                "OPENAI_API_KEY is not set. Add it to the .env file at the repo "
                "root (see .env.example), or set LLM_PROVIDER=claude."
            )
        from openai import AsyncOpenAI

        self._client = AsyncOpenAI(api_key=api_key)
        self._model = model

    async def stream_chat(
        self, messages: list[ChatMessage], system: str
    ) -> AsyncIterator[str]:
        """Stream the reply as text chunks (OpenAI puts the system prompt in
        the message list rather than a separate parameter)."""
        stream = await self._client.chat.completions.create(
            model=self._model,
            max_completion_tokens=MAX_TOKENS,
            stream=True,
            stream_options={"include_usage": True},
            messages=[
                {"role": "system", "content": system},
                *({"role": m.role, "content": m.content} for m in messages),
            ],
        )
        async for chunk in stream:
            if chunk.choices and chunk.choices[0].delta.content:
                yield chunk.choices[0].delta.content
            if chunk.usage:  # final chunk carries token counts
                logger.info(
                    "OpenAI call: %d input tokens, %d output tokens",
                    chunk.usage.prompt_tokens,
                    chunk.usage.completion_tokens,
                )
