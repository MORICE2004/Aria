"""Text chunking.

Long documents must be split before embedding: one vector per document would
blur many topics together, and retrieval should return the RELEVANT PARAGRAPH,
not a whole file. We split on paragraph boundaries and pack them into chunks
of roughly `max_chars`, with a one-paragraph overlap so an idea that spans a
boundary is never lost.
"""


def chunk_text(text: str, max_chars: int = 1200) -> list[str]:
    """Split text into chunks of at most ~max_chars, on paragraph boundaries."""
    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
    if not paragraphs:
        return []

    chunks: list[str] = []
    current: list[str] = []
    length = 0

    for paragraph in paragraphs:
        # A single paragraph longer than the limit gets hard-split.
        while len(paragraph) > max_chars:
            chunks.append(paragraph[:max_chars])
            paragraph = paragraph[max_chars:]
        if length + len(paragraph) > max_chars and current:
            chunks.append("\n\n".join(current))
            current = [current[-1]]  # overlap: carry the last paragraph forward
            length = len(current[0])
        current.append(paragraph)
        length += len(paragraph)

    if current:
        chunks.append("\n\n".join(current))
    return chunks
