"""Text extraction from uploaded files.

Deliberately model-free. Extraction is a mechanical problem with a right
answer, and using a model for it would turn a deterministic failure ("this
PDF is a scan, there is no text layer") into a plausible fabrication.

Every failure mode here is explicit, because the alternative — returning an
empty string — produces a document that looks ingested, searches as empty, and
teaches ARIA nothing while appearing to have worked.
"""

from __future__ import annotations

import io
import logging
import re
from dataclasses import dataclass

logger = logging.getLogger(__name__)

# Above this, a document is almost certainly not something MORICE meant to
# hand to a personal assistant, and chunking it would flood memory.
MAX_CHARACTERS = 2_000_000

# Below this, a PDF almost certainly has no text layer — it is a scan of
# paper. Saying so is far more useful than storing three characters of noise.
MIN_PDF_CHARACTERS = 40


class UnsupportedDocument(Exception):
    """The file cannot be read, with a reason MORICE can act on."""


@dataclass(frozen=True)
class ExtractedDocument:
    text: str
    # Where the text came from, for provenance and for the UI.
    format: str
    pages: int = 0
    # Section headings, when the format has them. Used to give the fact
    # extractor structure rather than an undifferentiated wall of text.
    sections: tuple[str, ...] = ()


def extract_text(data: bytes, filename: str) -> ExtractedDocument:
    """Pull readable text out of an uploaded file.

    Dispatches on extension rather than sniffing content: MORICE uploads files
    he named, and a wrong guess about a mislabelled file is more confusing
    than an honest "I do not read .xyz files".
    """
    name = filename.lower().strip()

    if name.endswith(".pdf"):
        return _extract_pdf(data)
    if name.endswith((".txt", ".md", ".markdown", ".csv", ".log", ".json")):
        return _extract_plain(data, name.rsplit(".", 1)[-1])

    raise UnsupportedDocument(
        f"ARIA cannot read '{filename}'. Supported: PDF, TXT, Markdown, CSV, "
        "JSON. For anything else, paste the text instead."
    )


def _extract_plain(data: bytes, fmt: str) -> ExtractedDocument:
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        # Latin-1 decodes any byte sequence, so this is a last resort that
        # cannot itself fail — better mangled accents than a lost document.
        text = data.decode("latin-1", errors="replace")
        logger.warning("Document was not valid UTF-8; decoded as latin-1")

    text = _normalise(text)
    if not text.strip():
        raise UnsupportedDocument("The file is empty.")
    _check_size(text)
    return ExtractedDocument(text=text, format=fmt, sections=_headings(text))


def _extract_pdf(data: bytes) -> ExtractedDocument:
    try:
        from pypdf import PdfReader
    except ImportError as exc:  # pragma: no cover - dependency is declared
        raise UnsupportedDocument(
            "PDF support needs the 'pypdf' package (pip install -r requirements.txt)."
        ) from exc

    try:
        reader = PdfReader(io.BytesIO(data))
    except Exception as exc:  # noqa: BLE001 — pypdf raises many shapes
        raise UnsupportedDocument(f"That PDF could not be opened: {exc}") from exc

    if reader.is_encrypted:
        # Attempt the empty password, which is common for "protected" PDFs
        # that are really just flagged.
        try:
            reader.decrypt("")
        except Exception:  # noqa: BLE001
            raise UnsupportedDocument(
                "That PDF is password protected. Remove the password and try again."
            ) from None

    pages: list[str] = []
    for index, page in enumerate(reader.pages):
        try:
            pages.append(page.extract_text() or "")
        except Exception as exc:  # noqa: BLE001 — one bad page must not lose the rest
            logger.warning("Could not extract page %d: %s", index + 1, exc)
            pages.append("")

    text = _normalise("\n\n".join(p for p in pages if p.strip()))

    if len(text.strip()) < MIN_PDF_CHARACTERS:
        raise UnsupportedDocument(
            f"That PDF has no readable text ({len(text.strip())} characters "
            f"across {len(reader.pages)} pages). It is probably a scan or "
            "photos of pages, which needs OCR — ARIA does not do OCR yet."
        )

    _check_size(text)
    return ExtractedDocument(
        text=text, format="pdf", pages=len(reader.pages), sections=_headings(text)
    )


def _normalise(text: str) -> str:
    """Tidy extracted text without changing its meaning.

    PDF extraction in particular produces ragged whitespace and hyphenated
    line breaks; leaving them in makes chunk boundaries land badly and makes
    retrieved passages hard to read.
    """
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    # Re-join words split across a line break by hyphenation.
    text = re.sub(r"(\w)-\n(\w)", r"\1\2", text)
    # Collapse runs of blank lines to a single paragraph break.
    text = re.sub(r"\n{3,}", "\n\n", text)
    # Trim trailing spaces that PDFs leave on nearly every line.
    text = "\n".join(line.rstrip() for line in text.split("\n"))
    return text.strip()


def _headings(text: str) -> tuple[str, ...]:
    """Best-effort section headings.

    Markdown headings, then short standalone lines that look like titles.
    Used only to give the fact extractor structure, so a wrong guess costs
    nothing — which is why this is heuristic rather than a model call.
    """
    headings: list[str] = []
    for line in text.split("\n"):
        stripped = line.strip()
        if not stripped or len(stripped) > 80:
            continue
        if stripped.startswith("#"):
            headings.append(stripped.lstrip("#").strip())
        elif stripped.isupper() and len(stripped.split()) <= 8:
            headings.append(stripped.title())
    # Deduplicate, preserve order, and cap: a hundred headings is not structure.
    seen: dict[str, None] = {}
    for h in headings:
        seen.setdefault(h, None)
    return tuple(seen)[:25]


def _check_size(text: str) -> None:
    if len(text) > MAX_CHARACTERS:
        raise UnsupportedDocument(
            f"That document is {len(text):,} characters, over ARIA's "
            f"{MAX_CHARACTERS:,} limit. Split it, or upload the relevant part."
        )
