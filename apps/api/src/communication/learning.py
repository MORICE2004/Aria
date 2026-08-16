"""Learning service — turning evidence into a communication profile.

The loop from the product directive:

    OBSERVE -> ANALYZE -> STORE PATTERN -> GENERATE -> USER EDITS
            -> COMPARE -> LEARN -> IMPROVE

Two rules govern everything here:

1. **Never overfit.** One message is not a style. Confidence grows with
   evidence and is capped, so a single edit can nudge ARIA but never rewrite
   her understanding of how MORICE writes.
2. **Never fabricate.** Statistical dimensions come from counting real
   messages; explicit rules come from MORICE's own words. Every pattern can
   be traced to its evidence.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.communication import style
from src.models import Contact, LearningEvent, StylePattern, WhatsAppMessage

# Confidence curve: evidence / (evidence + K). K sets how much evidence is
# "enough". At K=8: 1 sample -> 0.11, 8 -> 0.50, 30 -> 0.79, 100 -> 0.93.
# Deliberately slow: ARIA should sound unsure until she has really seen a lot.
_CONFIDENCE_K = 8
_MAX_CONFIDENCE = 0.95

# An explicit instruction ("never write Dear Sir/Madam") is strong evidence
# immediately — he said it, ARIA didn't infer it.
_RULE_CONFIDENCE = 0.95

# Must match StylePattern.dimension's column width. Postgres enforces it;
# SQLite does not, so code must truncate rather than rely on tests catching it.
MAX_DIMENSION_LEN = 120

# Below this, a pattern is too weak to shape a draft.
_USABLE_CONFIDENCE = 0.25


def confidence_for(evidence_count: int) -> float:
    """Confidence from evidence volume. Monotonic, capped, never certain."""
    if evidence_count <= 0:
        return 0.0
    raw = evidence_count / (evidence_count + _CONFIDENCE_K)
    return round(min(raw, _MAX_CONFIDENCE), 3)


def scope_for_contact(contact: Contact | None) -> str:
    """Most specific scope available for a contact."""
    if contact is None:
        return "global"
    return f"contact:{contact.id}"


async def _upsert_pattern(
    session: AsyncSession,
    *,
    dimension: str,
    scope: str,
    value: str,
    evidence_count: int,
    source: str,
    confidence: float | None = None,
) -> StylePattern:
    """Create or update one pattern, recomputing confidence from evidence."""
    result = await session.execute(
        select(StylePattern).where(
            StylePattern.dimension == dimension, StylePattern.scope == scope
        )
    )
    pattern = result.scalar_one_or_none()
    resolved_confidence = (
        confidence if confidence is not None else confidence_for(evidence_count)
    )

    if pattern is None:
        pattern = StylePattern(
            dimension=dimension,
            scope=scope,
            value=value,
            evidence_count=evidence_count,
            confidence=resolved_confidence,
            source=source,
        )
        session.add(pattern)
    else:
        pattern.value = value
        pattern.evidence_count = evidence_count
        pattern.confidence = resolved_confidence
        pattern.source = source
        pattern.updated_at = datetime.now(timezone.utc)
    return pattern


async def refresh_from_messages(
    session: AsyncSession, contact: Contact | None = None
) -> dict[str, str]:
    """Re-measure style from MORICE's own observed messages.

    Only `direction == "out"` messages are used — those are the ones he
    wrote. Inbound messages are other people's voices and must never shape
    how ARIA writes as him.
    """
    query = select(WhatsAppMessage).where(WhatsAppMessage.direction == "out")
    if contact is not None:
        query = query.where(WhatsAppMessage.contact_id == contact.id)
    rows = (await session.execute(query)).scalars()
    texts = [m.body for m in rows]

    metrics = style.analyze(texts)
    if metrics.sample_size == 0:
        return {}

    scope = scope_for_contact(contact)
    dimensions = metrics.as_dimensions()
    for dimension, value in dimensions.items():
        await _upsert_pattern(
            session,
            dimension=dimension,
            scope=scope,
            value=value,
            evidence_count=metrics.sample_size,
            source="observed",
        )
    await session.commit()
    return dimensions


async def record_feedback(
    session: AsyncSession,
    *,
    kind: str,
    draft: str = "",
    final: str = "",
    contact_id: str | None = None,
    note: str = "",
) -> tuple[LearningEvent, list[str]]:
    """Record an approval/edit/rejection and learn from the difference.

    Returns the event plus the human-readable lessons drawn from it, so the
    UI can show MORICE exactly what ARIA took away — no silent learning.
    """
    event = LearningEvent(
        kind=kind, draft=draft, final=final, contact_id=contact_id, note=note
    )
    session.add(event)

    lessons: list[str] = []
    if kind == "edited" and draft and final:
        lessons = style.diff_summary(draft, final)

        scope = f"contact:{contact_id}" if contact_id else "global"
        for lesson in lessons:
            # Each distinct lesson is its own pattern. Keying them all on a
            # shared "edit_preference" dimension made multiple lessons from
            # one edit overwrite each other, so nothing ever accumulated
            # evidence — a preference could never become confident.
            # Hard-truncated to the column width. Postgres enforces this even
            # though SQLite (used in tests) does not.
            dimension = f"edit:{lesson}"[:MAX_DIMENSION_LEN]
            existing = (
                await session.execute(
                    select(StylePattern).where(
                        StylePattern.dimension == dimension,
                        StylePattern.scope == scope,
                    )
                )
            ).scalar_one_or_none()
            count = (existing.evidence_count if existing else 0) + 1
            await _upsert_pattern(
                session,
                dimension=dimension,
                scope=scope,
                value=lesson,
                evidence_count=count,
                source="edit",
            )

    await session.commit()
    return event, lessons


async def add_rule(
    session: AsyncSession, *, rule: str, contact_id: str | None = None
) -> StylePattern:
    """Training mode: MORICE states a preference directly.

    Stored at high confidence immediately — an explicit instruction is not a
    guess. Kept as its own dimension so rules always survive re-analysis of
    the statistical dimensions.
    """
    scope = f"contact:{contact_id}" if contact_id else "global"
    session.add(LearningEvent(kind="rule", note=rule, contact_id=contact_id))
    pattern = await _upsert_pattern(
        session,
        dimension=f"rule:{rule}"[:MAX_DIMENSION_LEN],
        scope=scope,
        value=rule,
        evidence_count=1,
        source="explicit",
        confidence=_RULE_CONFIDENCE,
    )
    await session.commit()
    return pattern


async def list_patterns(
    session: AsyncSession, scope: str | None = None
) -> list[StylePattern]:
    query = select(StylePattern).order_by(
        StylePattern.confidence.desc(), StylePattern.dimension
    )
    if scope:
        query = query.where(StylePattern.scope == scope)
    return list((await session.execute(query)).scalars())


async def forget_pattern(session: AsyncSession, pattern_id: str) -> bool:
    """Delete a learned pattern. MORICE must be able to correct ARIA."""
    pattern = await session.get(StylePattern, pattern_id)
    if pattern is None:
        return False
    await session.delete(pattern)
    await session.commit()
    return True


async def build_profile_block(
    session: AsyncSession, contact: Contact | None = None
) -> str:
    """Assemble the style guidance injected into drafting prompts.

    Specific scopes override global ones on the same dimension, because how
    he writes to one person beats how he writes in general. Weak patterns are
    omitted entirely rather than presented as fact.
    """
    scopes = ["global"]
    if contact is not None:
        if contact.relationship and contact.relationship != "unknown":
            scopes.append(f"relationship:{contact.relationship}")
        scopes.append(f"contact:{contact.id}")

    # Later scopes win; rules accumulate rather than overwrite.
    chosen: dict[str, StylePattern] = {}
    rules: list[StylePattern] = []
    for scope in scopes:
        for pattern in await list_patterns(session, scope):
            if pattern.confidence < _USABLE_CONFIDENCE:
                continue
            if pattern.dimension.startswith("rule:"):
                rules.append(pattern)
            else:
                chosen[pattern.dimension] = pattern

    if not chosen and not rules:
        return (
            "No style profile yet — ARIA has not observed enough of MORICE's "
            "writing. Write naturally and neutrally; do not invent a voice."
        )

    lines = ["MORICE'S WRITING STYLE (learned from his real messages):"]
    for pattern in sorted(chosen.values(), key=lambda p: -p.confidence):
        lines.append(
            f"- {pattern.dimension}: {pattern.value} "
            f"[confidence {pattern.confidence:.2f}, {pattern.evidence_count} samples]"
        )
    if rules:
        lines.append("")
        lines.append("EXPLICIT RULES FROM MORICE (always obey these):")
        lines.extend(f"- {r.value}" for r in rules)

    lines.append("")
    lines.append(
        "Imitate these patterns. Where confidence is low, stay neutral rather "
        "than exaggerating the trait."
    )
    return "\n".join(lines)
