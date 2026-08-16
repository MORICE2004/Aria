"""Research agent — answering questions properly, with sources.

**What this can and cannot do, stated up front.** ARIA has no web access: no
search API key is configured, and there is no browser. So this agent researches
ARIA's OWN corpus — semantic memory, uploaded documents, observed
conversations — and says so in every answer.

That is a real limitation, not a disguised one. The alternative would be a
model answering from training data while looking like it did research, which
is the single most misleading thing a "research agent" can do. Every finding
here points at something ARIA actually holds.

Web search is a `SourceProvider` away: the interface below is the same shape
as the LLM provider abstraction, so adding Brave or Tavily is one adapter and
one key, not a rewrite. Until that exists, ARIA reports what she has and is
explicit about what she does not.

The loop:

    PLAN      break the question into sub-questions
    GATHER    search every source for each sub-question
    SYNTHESIZE  answer from what was found, citing it
    RECORD    store findings with provenance
"""

from src.research.agent import (  # noqa: F401
    Finding,
    ResearchAgent,
    ResearchReport,
    get_research_agent,
)
from src.research.sources import (  # noqa: F401
    DocumentSource,
    MemorySource,
    SourceProvider,
    SourceResult,
)
