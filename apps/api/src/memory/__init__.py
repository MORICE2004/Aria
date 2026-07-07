"""Memory package — ARIA's long-term semantic memory (RAG).

Pipeline: text -> chunks -> embeddings (vectors) -> pgvector -> similarity search.
The chat endpoint queries this before every reply, so ARIA "remembers".
"""

from functools import lru_cache

# NOTE: imports happen inside the functions, not at module top. src/models.py
# imports src.memory.embeddings (for EMBEDDING_DIM), which loads this package
# __init__ first — importing service/models here would be a circular import.


@lru_cache
def _cached_embedder():
    from src.memory.embeddings import FastEmbedProvider

    return FastEmbedProvider()


def get_memory_service():
    """FastAPI dependency. Tests override this with a fake embedder."""
    from src.memory.service import MemoryService

    return MemoryService(embedder=_cached_embedder())
