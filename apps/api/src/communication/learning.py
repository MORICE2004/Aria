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

from dataclasses import dataclass
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


def samples_needed_for(target_confidence: float) -> int:
    """How many of MORICE's messages would reach a given confidence.

    The inverse of the curve above. Exists so ARIA can answer "how much more
    do you need?" with a number instead of "keep going" — the difference
    between a system that feels stuck and one with a visible finish line.
    """
    if target_confidence <= 0:
        return 0
    if target_confidence >= _MAX_CONFIDENCE:
        target_confidence = _MAX_CONFIDENCE
    # n / (n + K) = c  ->  n = cK / (1 - c)
    import math

    return math.ceil(target_confidence * _CONFIDENCE_K / (1 - target_confidence))


# Below this much evidence, a per-relationship or per-contact measurement is an
# impression rather than a measurement, and writing it would do active harm:
# every scope ARIA adds is averaged into the confidence the autonomy gate reads,
# so three observed messages to his boss would drag down her certainty about a
# voice she actually knows well. Silence is the honest answer until there is
# enough to measure.
MIN_SAMPLES_FOR_SCOPE = 12


def scope_for_contact(contact: Contact | None) -> str:
    """Most specific scope available for a contact."""
    if contact is None:
        return "global"
    return f"contact:{contact.id}"


def scope_for_relationship(relationship: str) -> str:
    return f"relationship:{relationship}"


def describe_scope(scope: str) -> str:
    """Plain English for a scope, for the profile view and prompt blocks."""
    if scope == "global":
        return "how he writes in general"
    if scope.startswith("relationship:"):
        return f"how he writes to {scope.split(':', 1)[1]} contacts"
    if scope.startswith("contact:"):
        return "how he writes to this person"
    return scope


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


async def collect_own_writing(
    session: AsyncSession,
    contact: Contact | None = None,
    *,
    relationship: str | None = None,
    audience_only: bool = False,
) -> list[str]:
    """Every piece of text MORICE actually wrote, for style measurement.

    Three sources, all genuinely his words:

      1. **Outbound WhatsApp messages** — what he sent to real people.
      2. **His corrections** — when he rewrites one of ARIA's drafts, the
         final text is his. These were previously used only to derive
         "prefers shorter" style lessons, and were not counted as writing
         at all, which threw away the single most deliberate example of how
         he wanted a message to read.
      3. **Writing samples he added explicitly** (`kind="style"` memories),
         restricted to those whose audience matches what is being measured.

    Deliberately NOT included: his chat messages to ARIA. Those are his
    words, but a different register — nobody talks to their assistant the
    way they text a friend — and blending them would make ARIA's WhatsApp
    voice sound like his ARIA voice. Inbound messages are excluded for the
    stronger reason that they are other people's voices.

    Three ways to narrow it:

    * `contact` — only what he wrote to that person.
    * `relationship` — only what he wrote to people of that type.
    * `audience_only` — for the global scope, only writing with no particular
      audience: samples he offered as examples of how he writes in general.
      This is what keeps a partner's phrases out of his general voice.
    """
    from src.models import MemoryItem

    texts: list[str] = []

    if not audience_only:
        query = select(WhatsAppMessage).where(WhatsAppMessage.direction == "out")
        if contact is not None:
            query = query.where(WhatsAppMessage.contact_id == contact.id)
        elif relationship is not None:
            query = query.join(
                Contact, WhatsAppMessage.contact_id == Contact.id
            ).where(Contact.relationship == relationship)
        texts.extend(m.body for m in (await session.execute(query)).scalars())

        # What he rewrote a draft into. Scoped the same way as messages.
        corrections = select(LearningEvent).where(
            LearningEvent.kind == "edited", LearningEvent.final != ""
        )
        if contact is not None:
            corrections = corrections.where(LearningEvent.contact_id == contact.id)
        elif relationship is not None:
            corrections = corrections.join(
                Contact, LearningEvent.contact_id == Contact.id
            ).where(Contact.relationship == relationship)
        texts.extend(e.final for e in (await session.execute(corrections)).scalars())

    # Explicit writing samples, filtered by the audience he gave them for.
    # A chat export from one person is evidence about that person's scope; a
    # block he pasted with no audience is evidence about his general voice.
    sample_query = select(MemoryItem).where(MemoryItem.kind == "style")
    if contact is not None:
        sample_query = sample_query.where(
            MemoryItem.style_scope == f"contact:{contact.id}"
        )
    elif relationship is not None:
        sample_query = sample_query.where(
            MemoryItem.style_scope == scope_for_relationship(relationship)
        )
    elif audience_only:
        sample_query = sample_query.where(MemoryItem.style_scope == "global")
    # Otherwise: every sample, whoever it was written to. Measuring how long
    # his messages are, or how often he mixes Kiswahili, is better served by
    # all of his writing than by the part of it with no named audience.

    samples = await session.execute(sample_query)
    for item in samples.scalars():
        # A pasted block of several messages is several samples, not one
        # long one — otherwise "average words per message" measures the
        # size of his paste rather than the length of his messages.
        texts.extend(
            line.strip() for line in item.content.splitlines() if line.strip()
        )

    return [t for t in texts if t and t.strip()]


async def refresh_from_messages(
    session: AsyncSession, contact: Contact | None = None
) -> dict[str, str]:
    """Re-measure style from everything MORICE has actually written.

    For a contact this measures only what he wrote to that person. For the
    global scope it measures two pools rather than one, which is the whole
    point of the split:

    * **Shape** — length, rhythm, punctuation, language mix — from everything
      he has written. These generalise: he is a short, lowercase writer whether
      he is texting a friend or a recruiter.
    * **Words** — greetings, sign-offs, recurring phrases — only from writing
      with no particular audience. A phrase he uses with his partner is
      genuinely his and still has no business appearing in a reply to a
      client, so it never becomes part of his general voice. It is learned
      instead at the scope it belongs to, and used there.
    """
    texts = await collect_own_writing(session, contact)

    metrics = style.analyze(texts)
    if metrics.sample_size == 0:
        return {}

    scope = scope_for_contact(contact)
    dimensions = metrics.as_dimensions()

    # Lexical evidence is the audience-free pool for the global scope, and the
    # contact's own messages for a contact scope.
    lexical_evidence = metrics.sample_size

    if contact is None:
        general = style.analyze(
            await collect_own_writing(session, audience_only=True)
        )
        lexical_evidence = general.sample_size
        general_dimensions = general.as_dimensions()
        for dimension in list(dimensions):
            if not style.is_lexical(dimension):
                continue
            # Keep the audience-free reading of this dimension, or drop the
            # dimension entirely when there is no audience-free evidence for
            # it. Dropping means deleting: a phrase learned before scoping
            # existed must not survive as a global rule.
            if dimension in general_dimensions:
                dimensions[dimension] = general_dimensions[dimension]
            else:
                del dimensions[dimension]
                await _delete_pattern(session, dimension=dimension, scope=scope)

    for dimension, value in dimensions.items():
        # Lexical dimensions carry their own evidence count: it is the size of
        # the pool they were actually measured from, not of everything he has
        # ever written. Overstating it would overstate ARIA's confidence.
        evidence = (
            lexical_evidence if style.is_lexical(dimension) else metrics.sample_size
        )
        await _upsert_pattern(
            session,
            dimension=dimension,
            scope=scope,
            value=value,
            evidence_count=evidence,
            source="observed",
        )
    await session.commit()
    return dimensions


async def _delete_pattern(
    session: AsyncSession, *, dimension: str, scope: str
) -> None:
    existing = (
        await session.execute(
            select(StylePattern).where(
                StylePattern.dimension == dimension, StylePattern.scope == scope
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        await session.delete(existing)


async def refresh_all_scopes(session: AsyncSession) -> dict[str, int]:
    """Re-measure every scope ARIA has enough evidence to measure.

    Returns scope -> sample size for the scopes that were written, so the
    caller can report what was actually learned rather than claiming a
    profile exists for everyone.

    Scopes with less than `MIN_SAMPLES_FOR_SCOPE` behind them are skipped, not
    written weakly. See the constant for why that matters more than it looks.
    """
    written: dict[str, int] = {}

    dimensions = await refresh_from_messages(session)
    if dimensions:
        patterns = await list_patterns(session, "global")
        written["global"] = max((p.evidence_count for p in patterns), default=0)

    relationships = (
        await session.execute(
            select(Contact.relationship)
            .where(Contact.relationship != "", Contact.relationship != "unknown")
            .distinct()
        )
    ).scalars()

    for relationship in list(relationships):
        texts = await collect_own_writing(session, relationship=relationship)
        if len(texts) < MIN_SAMPLES_FOR_SCOPE:
            continue
        metrics = style.analyze(texts)
        scope = scope_for_relationship(relationship)
        for dimension, value in metrics.as_dimensions().items():
            await _upsert_pattern(
                session,
                dimension=dimension,
                scope=scope,
                value=value,
                evidence_count=metrics.sample_size,
                source="observed",
            )
        written[scope] = metrics.sample_size

    contacts = (await session.execute(select(Contact))).scalars()
    for contact in list(contacts):
        texts = await collect_own_writing(session, contact)
        if len(texts) < MIN_SAMPLES_FOR_SCOPE:
            continue
        metrics = style.analyze(texts)
        for dimension, value in metrics.as_dimensions().items():
            await _upsert_pattern(
                session,
                dimension=dimension,
                scope=f"contact:{contact.id}",
                value=value,
                evidence_count=metrics.sample_size,
                source="observed",
            )
        written[f"contact:{contact.id}"] = metrics.sample_size

    await session.commit()
    return written


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


@dataclass(frozen=True)
class ScopeSummary:
    """One layer of the profile, described for MORICE rather than for code."""

    scope: str
    description: str
    pattern_count: int
    evidence: int
    confidence: float


async def summarise_scopes(session: AsyncSession) -> list[ScopeSummary]:
    """Every layer ARIA has actually learned, general first.

    Exists so the profile view can show that ARIA holds several voices rather
    than one — and which of them she would use for a given person.
    """
    patterns = await list_patterns(session)
    by_scope: dict[str, list[StylePattern]] = {}
    for pattern in patterns:
        by_scope.setdefault(pattern.scope, []).append(pattern)

    summaries: list[ScopeSummary] = []
    for scope, group in by_scope.items():
        usable = [p.confidence for p in group if p.confidence >= _USABLE_CONFIDENCE]
        summaries.append(
            ScopeSummary(
                scope=scope,
                description=describe_scope(scope),
                pattern_count=len(group),
                evidence=max((p.evidence_count for p in group), default=0),
                confidence=(
                    round(sum(usable) / len(usable), 3) if usable else 0.0
                ),
            )
        )

    # Global first, then relationships, then people: the order they compose in.
    def rank(summary: ScopeSummary) -> tuple[int, str]:
        prefix = (
            0
            if summary.scope == "global"
            else 1
            if summary.scope.startswith("relationship:")
            else 2
        )
        return prefix, summary.scope

    return sorted(summaries, key=rank)


async def forget_pattern(session: AsyncSession, pattern_id: str) -> bool:
    """Delete a learned pattern. MORICE must be able to correct ARIA."""
    pattern = await session.get(StylePattern, pattern_id)
    if pattern is None:
        return False
    await session.delete(pattern)
    await session.commit()
    return True


def scopes_for(contact: Contact | None) -> list[str]:
    """The layers that compose a reply's voice, least specific first.

    This is the product directive's formula in code:

        GENERAL PROFILE + RELATIONSHIP PROFILE + CONTACT PROFILE

    The remaining two terms — current conversation and current intent — are
    per-message rather than learned, so they are passed into the block below
    instead of being stored as patterns.
    """
    scopes = ["global"]
    if contact is not None:
        if contact.relationship and contact.relationship != "unknown":
            scopes.append(scope_for_relationship(contact.relationship))
        scopes.append(f"contact:{contact.id}")
    return scopes


async def build_profile_block(
    session: AsyncSession,
    contact: Contact | None = None,
    *,
    intent: str = "",
) -> str:
    """Assemble the style guidance injected into drafting prompts.

    Specific scopes override global ones on the same dimension, because how
    he writes to one person beats how he writes in general. Weak patterns are
    omitted entirely rather than presented as fact.

    Every line says which layer it came from. That is not decoration: when
    ARIA writes something that sounds wrong to MORICE, the first question is
    where she got it, and a profile that cannot answer that cannot be
    corrected.
    """
    scopes = scopes_for(contact)

    # Later scopes win; rules accumulate rather than overwrite.
    chosen: dict[str, tuple[StylePattern, str]] = {}
    rules: list[StylePattern] = []
    corrections: list[StylePattern] = []
    for scope in scopes:
        for pattern in await list_patterns(session, scope):
            if pattern.confidence < _USABLE_CONFIDENCE:
                continue
            if pattern.dimension.startswith("rule:"):
                rules.append(pattern)
            elif pattern.dimension.startswith("edit:"):
                # A correction is guidance, not a measurement; it reads as an
                # instruction rather than as a statistic.
                corrections.append(pattern)
            else:
                chosen[pattern.dimension] = (pattern, scope)

    if not chosen and not rules and not corrections:
        return (
            "No style profile yet — ARIA has not observed enough of MORICE's "
            "writing. Write naturally and neutrally; do not invent a voice."
        )

    lines = ["MORICE'S WRITING STYLE (learned from his real messages):"]
    for pattern, scope in sorted(chosen.values(), key=lambda pair: -pair[0].confidence):
        lines.append(
            f"- {pattern.dimension}: {pattern.value} "
            f"[{describe_scope(scope)}; confidence {pattern.confidence:.2f}, "
            f"{pattern.evidence_count} samples]"
        )
    if rules:
        lines.append("")
        lines.append("EXPLICIT RULES FROM MORICE (always obey these):")
        lines.extend(f"- {r.value}" for r in rules)
    if corrections:
        lines.append("")
        lines.append("WHAT HE CHANGED WHEN HE CORRECTED ARIA:")
        lines.extend(f"- {c.value}" for c in corrections)

    if intent:
        lines.append("")
        lines.append(
            f"What this particular message needs to do: {intent}. Stay in his "
            "voice while doing it — the purpose changes the content, not the "
            "way he writes."
        )

    lines.append("")
    lines.append(
        "Imitate these patterns. Where confidence is low, stay neutral rather "
        "than exaggerating the trait. Do not reuse a phrase listed for a "
        "different audience than this one."
    )
    return "\n".join(lines)
