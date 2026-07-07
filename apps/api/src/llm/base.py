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


class LLMProvider(ABC):
    """Contract all LLM adapters must fulfil."""

    @abstractmethod
    def stream_chat(
        self, messages: list[ChatMessage], system: str
    ) -> AsyncIterator[str]:
        """Send the conversation to the model and yield the reply as text
        chunks, so the UI can show words as they are generated instead of
        waiting for the full answer.
        """
        raise NotImplementedError
