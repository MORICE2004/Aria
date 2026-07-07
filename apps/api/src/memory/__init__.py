"""Memory package — ARIA's long-term semantic memory (RAG).

Pipeline: text -> chunks -> embeddings (vectors) -> pgvector -> similarity search.
The chat endpoint queries this before every reply, so ARIA "remembers".
"""

from functools import lru_cache

from src.memory.embeddings import EmbeddingProvider, FastEmbedProvider
from src.memory.service import MemoryService


@lru_cache
def _cached_embedder() -> EmbeddingProvider:
    return FastEmbedProvider()


def get_memory_service() -> MemoryService:
    """FastAPI dependency. Tests override this with a fake embedder."""
    return MemoryService(embedder=_cached_embedder())
