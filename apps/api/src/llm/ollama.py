"""Ollama adapter — local models, the ONLY file that talks to the Ollama API.

Why this matters for ARIA: local inference is free, private, and works
offline. Personal content never leaves the machine, which is the same
principle behind our local embeddings (see src/memory/embeddings.py).

Uses Ollama's native /api/chat over httpx (already a dependency — no new
package). Ollama streams newline-delimited JSON rather than SSE.
"""

import json
import logging
from collections.abc import AsyncIterator

import httpx

from src.llm.base import ChatMessage, LLMProvider

logger = logging.getLogger(__name__)

# Local models can be slow on CPU; generous timeout, but not unbounded.
REQUEST_TIMEOUT = httpx.Timeout(300.0, connect=5.0)


class OllamaUnavailable(RuntimeError):
    """Ollama isn't running, or the requested model isn't pulled."""


class OllamaProvider(LLMProvider):
    def __init__(self, base_url: str, model: str) -> None:
        self._base_url = base_url.rstrip("/")
        self._model = model

    @property
    def model_name(self) -> str:
        return self._model

    async def stream_chat(
        self, messages: list[ChatMessage], system: str
    ) -> AsyncIterator[str]:
        """Stream the reply as text chunks from a local model."""
        payload = {
            "model": self._model,
            "stream": True,
            "messages": [
                {"role": "system", "content": system},
                *({"role": m.role, "content": m.content} for m in messages),
            ],
        }

        async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
            try:
                async with client.stream(
                    "POST", f"{self._base_url}/api/chat", json=payload
                ) as response:
                    if response.status_code == 404:
                        # Ollama returns 404 when the model isn't pulled.
                        raise OllamaUnavailable(
                            f"Ollama model {self._model!r} is not installed. "
                            f"Run: ollama pull {self._model}"
                        )
                    response.raise_for_status()

                    async for line in response.aiter_lines():
                        if not line.strip():
                            continue
                        try:
                            chunk = json.loads(line)
                        except json.JSONDecodeError:
                            continue  # tolerate keep-alive / partial lines
                        content = chunk.get("message", {}).get("content")
                        if content:
                            yield content
                        if chunk.get("done"):
                            # Final chunk carries token counts; log for cost parity
                            # with cloud providers (local cost is zero, but usage
                            # still tells us how much work ran where).
                            logger.info(
                                "Ollama call (%s): %s input tokens, %s output tokens",
                                self._model,
                                chunk.get("prompt_eval_count", "?"),
                                chunk.get("eval_count", "?"),
                            )
            except httpx.ConnectError as exc:
                raise OllamaUnavailable(
                    "Ollama is not running. Start it (the Ollama app, or "
                    "`ollama serve`) — or set LLM_PROVIDER to a cloud provider."
                ) from exc
