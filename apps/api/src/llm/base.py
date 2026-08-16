"""The LLM provider interface.

Every provider (Claude today; OpenAI or a local model tomorrow) implements
this one contract. Agents and routers depend on THIS, never on a vendor SDK.
"""

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from dataclasses import dataclass


@dataclass(frozen=True)
class ChatMessage:
    """One turn of a conversation, vendor-neutral."""

    role: str  # "user" | "assistant"
    content: str


@dataclass(frozen=True)
class Usage:
    """Token counts from one completed call. Facts, not estimates."""

    input_tokens: int
    output_tokens: int


class LLMProvider(ABC):
    """Contract all LLM adapters must fulfil.

    After `stream_chat` is fully consumed, adapters set `last_usage` so the
    caller can record what the call actually cost. It is an attribute rather
    than a return value because the method is a generator — and optional, so
    an adapter that cannot report usage simply leaves it None.
    """

    last_usage: "Usage | None" = None

    @abstractmethod
    def stream_chat(
        self, messages: list[ChatMessage], system: str
    ) -> AsyncIterator[str]:
        """Send the conversation to the model and yield the reply as text
        chunks, so the UI can show words as they are generated instead of
        waiting for the full answer.
        """
        raise NotImplementedError
