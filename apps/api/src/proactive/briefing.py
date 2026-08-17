"""The daily briefing — "ARIA, what happened while I was away?"

This answers a different question from the proactive engine next door, and the
difference is worth stating because it decides what belongs here.

`engine.py` produces INSIGHTS: standing concerns, deduplicated, said once, with
a cooldown, because an assistant that repeats itself is one you learn to
ignore. Those are things that are *wrong*.

A briefing is an ACCOUNT OF A PERIOD: what arrived, what ARIA did about it,
what she is waiting on, what she learned, what it cost. Most of it is not a
problem at all, and it is worth saying every time he asks, because "nothing
happened" is a useful answer to "what did I miss?" — where it would be
worthless as an insight.

Two rules, both from the product directive and both enforced by construction:

* **Nothing is fabricated.** Every number here is a count of rows and every
  name comes from a record. Where there is nothing to report, the briefing
  says so rather than filling the space. Sections with no content are omitted
  entirely, so an empty briefing looks empty instead of looking broken.

* **No model writes it.** The briefing is assembled by code, not summarised by
  an LLM. A model asked to summarise activity will smooth over the gaps and
  occasionally invent a plausible item, and the one report MORICE should be
  able to trust completely is the one telling him what his assistant did in
  his name while he was not watching.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core import clock
from src.models import (
    ActionRequest,
    AutonomousResponse,
    Contact,
    InboundMessage,
    Insight,
    MessageDraft,
    ModelUsage,
    OutboundMessage,
    Task,
    WhatsAppMessage,
)

# The default window. A day is the natural unit for "while I was away", and it
# is also long enough that an empty briefing is genuinely informative.
DEFAULT_HOURS = 24

# Cap on named items in any one section. A briefing that lists forty messages
# is not a briefing.
MAX_ITEMS = 8


@dataclass(frozen=True)
class Item:
    """One concrete thing, with enough detail to act on it."""

    title: str
    detail: str = ""
    link: str = ""
    # Set when this item is a record ARIA can explain in full.
    reference_id: str = ""


@dataclass(frozen=True)
class Section:
    """One part of the briefing. Omitted entirely when it has nothing to say."""

    key: str
    heading: str
    summary: str
    items: list[Item] = field(default_factory=list)
    # True when this section needs MORICE to do something, as opposed to
    # merely telling him what happened.
    needs_attention: bool = False


@dataclass(frozen=True)
class Briefing:
    since: datetime
    until: datetime
    hours: float
    headline: str
    sections: list[Section]
    # Deliberately separate from the sections: this is the honest answer when
    # there is nothing to report, and it must be impossible to confuse with
    # "ARIA could not tell".
    quiet: bool


async def build(
    session: AsyncSession, *, hours: float = DEFAULT_HOURS
) -> Briefing:
    """Assemble the briefing for the last `hours`."""
    until = clock.now()
    since = until - timedelta(hours=hours)

    sections = [
        section
        for section in (
            await _messages_that_arrived(session, since),
            await _what_aria_handled(session, since),
            await _waiting_on_morice(session),
            await _what_needs_a_reply(session, since),
            await _due_and_overdue(session),
            await _what_went_wrong(session, since),
            await _what_aria_noticed(session),
            await _what_it_cost(session, since),
        )
        if section is not None
    ]

    attention = [s for s in sections if s.needs_attention]
    if not sections:
        headline = (
            f"Nothing happened in the last {_period(hours)}. No messages, no "
            "actions, nothing waiting."
        )
    elif attention:
        headline = "; ".join(s.summary for s in attention[:3])
    else:
        headline = sections[0].summary

    return Briefing(
        since=since,
        until=until,
        hours=hours,
        headline=headline,
        sections=sections,
        quiet=not sections,
    )


def _period(hours: float) -> str:
    if hours <= 1:
        return "hour"
    if abs(hours - 24) < 0.01:
        return "day"
    if hours < 24:
        return f"{hours:g} hours"
    return f"{hours / 24:g} days"


_IRREGULAR_PLURALS = {"person": "people", "reply": "replies"}


def _plural(count: int, noun: str) -> str:
    if count == 1:
        return f"{count} {noun}"
    return f"{count} {_IRREGULAR_PLURALS.get(noun, noun + 's')}"


async def _messages_that_arrived(
    session: AsyncSession, since: datetime
) -> Section | None:
    rows = list(
        (
            await session.execute(
                select(WhatsAppMessage, Contact)
                .join(Contact, WhatsAppMessage.contact_id == Contact.id)
                .where(
                    WhatsAppMessage.direction == "in",
                    WhatsAppMessage.sent_at >= since,
                )
                .order_by(WhatsAppMessage.sent_at.desc())
            )
        ).all()
    )
    if not rows:
        return None

    senders: dict[str, int] = {}
    for _, contact in rows:
        senders[contact.name] = senders.get(contact.name, 0) + 1

    return Section(
        key="messages",
        heading="Messages that came in",
        summary=(
            f"{_plural(len(rows), 'message')} from "
            f"{_plural(len(senders), 'person')}"
        ),
        items=[
            Item(
                title=f"{name} — {_plural(count, 'message')}",
                link="/whatsapp",
            )
            for name, count in sorted(senders.items(), key=lambda kv: -kv[1])[
                :MAX_ITEMS
            ]
        ],
    )


async def _what_aria_handled(
    session: AsyncSession, since: datetime
) -> Section | None:
    """Replies ARIA sent on her own — the part he most needs to see.

    Reported by what actually happened to each one, not by what was decided:
    "sent" and "still queued because no device is linked" are different facts,
    and collapsing them into "handled" is exactly the kind of comfortable
    summary this module exists to avoid.
    """
    rows = list(
        (
            await session.execute(
                select(AutonomousResponse, Contact)
                .join(Contact, AutonomousResponse.contact_id == Contact.id)
                .where(
                    AutonomousResponse.created_at >= since,
                    AutonomousResponse.decision == "auto_send",
                )
                .order_by(AutonomousResponse.created_at.desc())
            )
        ).all()
    )
    if not rows:
        return None

    by_status: dict[str, int] = {}
    for response, _ in rows:
        by_status[response.send_status] = by_status.get(response.send_status, 0) + 1

    parts = []
    if by_status.get("sent"):
        parts.append(f"{_plural(by_status['sent'], 'reply')} sent")
    for status in ("queued", "failed", "blocked"):
        if by_status.get(status):
            parts.append(f"{by_status[status]} {status}")

    unreviewed = sum(1 for r, _ in rows if r.user_reaction == "none")

    return Section(
        key="handled",
        heading="What ARIA handled on her own",
        summary=", ".join(parts),
        needs_attention=unreviewed > 0,
        items=[
            Item(
                title=f"To {contact.name}: {response.response[:90]}",
                detail=(
                    f"{response.send_status}"
                    + (
                        f" — {response.send_error[:120]}"
                        if response.send_error
                        else ""
                    )
                    + f"; risk {response.risk_level or 'unknown'}"
                    + f"; {response.action_type or 'reply'}"
                    + (
                        "; you have not reviewed it"
                        if response.user_reaction == "none"
                        else f"; you {response.user_reaction} it"
                    )
                ),
                link="/activity",
                reference_id=response.id,
            )
            for response, contact in rows[:MAX_ITEMS]
        ],
    )


async def _waiting_on_morice(session: AsyncSession) -> Section | None:
    pending = list(
        (
            await session.execute(
                select(ActionRequest)
                .where(ActionRequest.status == "pending")
                .order_by(ActionRequest.created_at)
            )
        ).scalars()
    )
    if not pending:
        return None
    return Section(
        key="approvals",
        heading="Waiting for your decision",
        summary=f"{_plural(len(pending), 'action')} waiting for approval",
        needs_attention=True,
        items=[
            Item(title=a.summary, detail=a.action_type, link="/approvals", reference_id=a.id)
            for a in pending[:MAX_ITEMS]
        ],
    )


async def _what_needs_a_reply(
    session: AsyncSession, since: datetime
) -> Section | None:
    """Drafts ARIA prepared but did not send, and is waiting on."""
    rows = list(
        (
            await session.execute(
                select(MessageDraft, Contact)
                .join(Contact, MessageDraft.contact_id == Contact.id)
                .where(
                    MessageDraft.status == "pending",
                    MessageDraft.created_at >= since,
                )
                .order_by(MessageDraft.created_at.desc())
            )
        ).all()
    )
    if not rows:
        return None
    return Section(
        key="drafts",
        heading="Replies ARIA drafted for you",
        summary=f"{_plural(len(rows), 'draft')} ready to send or correct",
        needs_attention=True,
        items=[
            Item(
                title=f"To {contact.name}: {draft.draft[:90]}",
                detail=f"in reply to: {draft.incoming[:80]}",
                link="/messages",
                reference_id=draft.id,
            )
            for draft, contact in rows[:MAX_ITEMS]
        ],
    )


async def _due_and_overdue(session: AsyncSession) -> Section | None:
    """Tasks due within the day, plus anything already late.

    Not windowed by the briefing period: a deadline he missed last week is
    still today's problem.
    """
    now = clock.now()
    horizon = now + timedelta(hours=DEFAULT_HOURS)
    rows = list(
        (
            await session.execute(
                select(Task)
                .where(
                    Task.status == "open",
                    Task.due_at.is_not(None),
                    Task.due_at <= horizon,
                )
                .order_by(Task.due_at)
            )
        ).scalars()
    )
    if not rows:
        return None

    overdue = [t for t in rows if (clock.as_utc(t.due_at) or now) < now]
    summary = f"{_plural(len(rows), 'task')} due"
    if overdue:
        summary += f", {len(overdue)} already overdue"

    return Section(
        key="tasks",
        heading="Due today",
        summary=summary,
        needs_attention=True,
        items=[
            Item(
                title=task.title,
                detail=(
                    ("overdue — " if task in overdue else "")
                    + f"{task.kind}, due "
                    + (clock.as_utc(task.due_at).strftime("%a %H:%M") if task.due_at else "")
                ),
                link="/tasks",
                reference_id=task.id,
            )
            for task in rows[:MAX_ITEMS]
        ],
    )


async def _what_went_wrong(
    session: AsyncSession, since: datetime
) -> Section | None:
    """Failures, stated plainly. ARIA never reports a failure as a success."""
    items: list[Item] = []

    dead = list(
        (
            await session.execute(
                select(InboundMessage)
                .where(
                    InboundMessage.status == "dead",
                    InboundMessage.received_at >= since,
                )
                .order_by(InboundMessage.received_at.desc())
            )
        ).scalars()
    )
    for row in dead[:MAX_ITEMS]:
        items.append(
            Item(
                title=f"Could not process a message from {row.name or row.handle}",
                detail=(row.last_error or "no error recorded")[:160],
                link="/activity",
                reference_id=row.id,
            )
        )

    failed = list(
        (
            await session.execute(
                select(OutboundMessage)
                .where(
                    OutboundMessage.status == "failed",
                    OutboundMessage.created_at >= since,
                )
                .order_by(OutboundMessage.created_at.desc())
            )
        ).scalars()
    )
    for row in failed[:MAX_ITEMS]:
        items.append(
            Item(
                title=f"A message to {row.handle} was not delivered",
                detail=(row.last_error or "no error recorded")[:160],
                link="/whatsapp",
                reference_id=row.id,
            )
        )

    if not items:
        return None
    return Section(
        key="failures",
        heading="What did not work",
        summary=f"{_plural(len(items), 'failure')} — nothing was silently dropped",
        needs_attention=True,
        items=items[:MAX_ITEMS],
    )


async def _what_aria_noticed(session: AsyncSession) -> Section | None:
    """Open proactive insights, referenced rather than restated.

    The engine already decides what is worth raising and how often; repeating
    that judgement here would mean two systems deciding the same thing badly.
    """
    rows = list(
        (
            await session.execute(
                select(Insight)
                .where(Insight.status == "open")
                .order_by(Insight.created_at.desc())
            )
        ).scalars()
    )
    if not rows:
        return None
    urgent = [r for r in rows if r.severity in ("warning", "urgent")]
    return Section(
        key="noticed",
        heading="Things ARIA noticed",
        summary=(
            f"{_plural(len(rows), 'observation')}"
            + (f", {len(urgent)} worth acting on" if urgent else "")
        ),
        needs_attention=bool(urgent),
        items=[
            Item(
                title=row.title,
                detail=row.action or row.detail[:160],
                link=row.link or "/",
                reference_id=row.id,
            )
            for row in rows[:MAX_ITEMS]
        ],
    )


async def _what_it_cost(session: AsyncSession, since: datetime) -> Section | None:
    calls, cost = (
        await session.execute(
            select(
                func.count(ModelUsage.id),
                func.coalesce(func.sum(ModelUsage.estimated_cost_usd), 0.0),
            ).where(ModelUsage.created_at >= since)
        )
    ).one()
    # Local calls are the one cost figure that is certain, so they are counted
    # rather than inferred from the estimate.
    local = (
        await session.execute(
            select(func.count(ModelUsage.id)).where(
                ModelUsage.created_at >= since,
                ModelUsage.tier.like("local%"),
            )
        )
    ).scalar_one() or 0
    if not calls:
        return None
    return Section(
        key="cost",
        heading="What it cost",
        summary=(
            f"{_plural(calls, 'model call')}, about ${cost:.4f} estimated"
            + (f"; {local} ran locally and free" if local else "")
        ),
        items=[],
    )
