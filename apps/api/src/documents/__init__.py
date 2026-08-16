"""Document intelligence — reading files so ARIA knows what is in them.

Three things happen to a document, in this order, and the order matters:

  1. **Extract text.** Deterministic, no model involved. If this fails, it
     fails loudly rather than handing an empty string downstream and
     producing a confident summary of nothing.

  2. **Store it whole, with provenance.** The document becomes a memory item
     that RAG can already search. This step alone makes the document useful,
     and it works even if step 3 breaks.

  3. **Extract facts.** A model reads the text and proposes durable facts.
     These are proposals, not truths: each one keeps a pointer back to the
     document it came from, and MORICE can reject any of them.

The separation exists because step 3 is the only unreliable one. A design
where extraction failure loses the document would trade a working feature for
a nicer-sounding one.
"""

from src.documents.extract import (  # noqa: F401
    ExtractedDocument,
    UnsupportedDocument,
    extract_text,
)
from src.documents.service import (  # noqa: F401
    DocumentService,
    get_document_service,
)
