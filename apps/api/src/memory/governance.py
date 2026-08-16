"""Memory governance — deciding what deserves to be remembered, and for how long.

The directive's requirement: ARIA must not store everything. A memory system
that hoards is a memory system that retrieves noise.

Three questions per memory:
  1. WHAT TYPE is it? (durable preference vs passing detail)
  2. HOW IMPORTANT is it? (drives retrieval order and cleanup suggestions)
  3. WHY do we have it? (provenance — so "why do you remember that?" has an answer)

Scoring is rule-based and inspectable rather than model-judged. A number a
model invented cannot be explained or reproduced; these can.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

# How long each type survives without being reinforced. None = forever.
TYPE_LIFETIMES: dict[str, timedelta | None] = {
    "longterm": None,       # stable facts about him
    "preference": None,     # how he likes things done
    "relationship": None,   # context about people
    "project": None,        # cleared when he says the project ended
    "episodic": timedelta(days=365),  # events fade after a year
    "transient": timedelta(days=7),   # passing details
}

MEMORY_TYPES = tuple(TYPE_LIFETIMES.keys())

# Phrases that signal MORICE wants something kept permanently.
_EXPLICIT_KEEP = re.compile(
    r"\b(remember (this|that)|don'?t forget|always|never|my (name|goal|birthday))\b",
    re.IGNORECASE,
)
# Phrases that signal something short-lived.
_TRANSIENT = re.compile(
    r"\b(today|tonight|tomorrow|this (morning|afternoon|evening|week)|"
    r"right now|at the moment|currently waiting)\b",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class Judgement:
    memory_type: str
    importance: float
    expires_at: datetime | None
    reason: str  # shown to MORICE; this is what makes the score auditable


def judge(
    *, title: str, content: str, kind: str, explicit: bool = False
) -> Judgement:
    """Decide type, importance and lifetime for a new memory.

    `explicit=True` means MORICE said "remember this" — which overrides
    every heuristic. His stated intent is not something to second-guess.
    """
    text = f"{title} {content}"
    reasons: list[str] = []

    if explicit:
        return Judgement(
            memory_type="longterm",
            importance=0.95,
            expires_at=None,
            reason="you asked ARIA to remember this",
        )

    # Kind gives a strong prior.
    if kind == "style":
        memory_type, importance = "preference", 0.8
        reasons.append("writing style is a durable preference")
    elif kind == "document":
        memory_type, importance = "longterm", 0.7
        reasons.append("documents are reference material")
    elif kind == "fact":
        memory_type, importance = "longterm", 0.7
        reasons.append("stated as a fact about you")
    else:
        memory_type, importance = "longterm", 0.5
        reasons.append("general note")

    if _EXPLICIT_KEEP.search(text):
        importance = min(1.0, importance + 0.2)
        reasons.append("contains lasting-preference wording")

    if _TRANSIENT.search(text):
        memory_type = "transient"
        importance = min(importance, 0.3)
        reasons.append("mentions a short-lived timeframe")

    # Very short notes carry little; very long ones are usually documents.
    words = len(content.split())
    if words < 4:
        importance = min(importance, 0.35)
        reasons.append("very short")
    elif words > 200:
        importance = min(1.0, importance + 0.1)
        reasons.append("substantial content")

    lifetime = TYPE_LIFETIMES.get(memory_type)
    expires = datetime.now(timezone.utc) + lifetime if lifetime else None

    return Judgement(
        memory_type=memory_type,
        importance=round(importance, 2),
        expires_at=expires,
        reason="; ".join(reasons),
    )


def is_expired(expires_at: datetime | None, *, now: datetime | None = None) -> bool:
    if expires_at is None:
        return False
    current = now or datetime.now(timezone.utc)
    # Tolerate naive timestamps from SQLite.
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    return expires_at < current
