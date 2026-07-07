"""Embedding providers.

An embedding turns text into a list of numbers (a vector) such that texts
with similar MEANING get nearby vectors. That's what lets memory search find
"what do I know about my career goals?" even when no note contains those
exact words.

Same adapter pattern as src/llm: the rest of the app depends on
`EmbeddingProvider`, never on a specific library.
"""

from abc import ABC, abstractmethod

# All ARIA embeddings use this many dimensions; the DB column matches it.
EMBEDDING_DIM = 384


class EmbeddingProvider(ABC):
    @abstractmethod
    def embed(self, texts: list[str]) -> list[list[float]]:
        """Turn each text into a vector of EMBEDDING_DIM floats."""
        raise NotImplementedError


class FastEmbedProvider(EmbeddingProvider):
    """Local embeddings via fastembed (BAAI/bge-small-en-v1.5).

    Runs on the CPU — free and private: memory content never leaves the
    machine to be indexed. The model (~100 MB) downloads once on first use.
    """

    def __init__(self) -> None:
        # Imported here (not at module top) so the app can start even before
        # the optional model download has ever happened.
        from fastembed import TextEmbedding

        self._model = TextEmbedding("BAAI/bge-small-en-v1.5")

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [vector.tolist() for vector in self._model.embed(texts)]
