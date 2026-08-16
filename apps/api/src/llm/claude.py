"""Claude adapter — the ONLY file that imports the Anthropic SDK."""

import logging
from collections.abc import AsyncIterator

from anthropic import AsyncAnthropic

from src.llm.base import ChatMessage, LLMProvider, Usage

logger = logging.getLogger(__name__)

MODEL = "claude-sonnet-5"  # strong quality/cost balance for a personal assistant
MAX_TOKENS = 4096


class ClaudeProvider(LLMProvider):
    def __init__(self, api_key: str) -> None:
        if not api_key:
            raise ValueError(
                "ANTHROPIC_API_KEY is not set. Add it to the .env file at the "
                "repo root (see .env.example). Get a key at console.anthropic.com."
            )
        self._client = AsyncAnthropic(api_key=api_key)

    async def stream_chat(
        self, messages: list[ChatMessage], system: str
    ) -> AsyncIterator[str]:
        """Stream Claude's reply as text chunks."""
        async with self._client.messages.stream(
            model=MODEL,
            max_tokens=MAX_TOKENS,
            system=system,
            messages=[{"role": m.role, "content": m.content} for m in messages],
        ) as stream:
            async for text in stream.text_stream:
                yield text
            # Log token usage so spend is always visible (cost tracking, Phase 1).
            final = await stream.get_final_message()
            self.last_usage = Usage(
                input_tokens=final.usage.input_tokens,
                output_tokens=final.usage.output_tokens,
            )
            logger.info(
                "Claude call: %d input tokens, %d output tokens",
                final.usage.input_tokens,
                final.usage.output_tokens,
            )
