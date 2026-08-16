"""The proactive engine: checks that look for things worth mentioning.

Each check is a small function that reads state and returns zero or more
Insights. They are deliberately independent — one throwing must not silence
the others, because the check most likely to break is the one watching the
thing that is currently broken.

Insights are persisted rather than computed on demand. That is what makes
"say it once" possible across restarts, and it means MORICE can dismiss
something and have it stay dismissed.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.clock import as_utc, now as _now, seconds_since, seconds_until

from src.models import (
    ActionRequest,
    AutonomousResponse,
    Contact,
    InboundMessage,
    Insight as InsightRow,
    MessageDraft,
    Task,
)

logger = logging.getLogger(__name__)


class Severity(str, Enum):
    """How much this deserves to interrupt.

    Kept to three levels on purpose. Five-level severity scales collapse into
    "everything is medium" within a month.
    """

    FYI = "fyi"            # worth knowing, no hurry
    ATTENTION = "attention"  # should be looked at today
    URGENT = "urgent"      # something is wrong right now


@dataclass(frozen=True)
class Insight:
    # Stable across runs for the same underlying situation, so re-running a
    # check does not produce a second copy of the same observation.
    key: str
    severity: Severity
    title: str
    detail: str
    # Where MORICE should go to deal with it.
    link: str = ""
    # What he could do about it, in his own terms. An insight with no
    # actionable next step should not have been raised at all.
    action: str = ""


# A check reads state and reports. It is given a session and nothing else —
# no model router, no gateway — so it structurally cannot act.
Check = Callable[[AsyncSession], Awaitable[list[Insight]]]

_checks: dict[str, Check] = {}


def register_check(name: str) -> Callable[[Check], Check]:
    def decorator(func: Check) -> Check:
        if name in _checks:
            raise ValueError(f"Check {name!r} already registered")
        _checks[name] = func
        return func

    return decorator


# --- The checks -----------------------------------------------------------

@register_check("stuck_messages")
async def check_stuck_messages(session: AsyncSession) -> list[Insight]:
    """Messages that failed processing and gave up.

    The highest-value proactive check in the system: a dead-lettered message
    is a real WhatsApp message from a real person that ARIA received and never
    handled. Nobody will notice it on their own, because from the sender's
    side it looks like MORICE simply did not reply.
    """
    dead = list(
        (
            await session.execute(
                select(InboundMessage)
                .where(InboundMessage.status == "dead")
                .order_by(InboundMessage.received_at.desc())
                .limit(10)
            )
        ).scalars()
    )
    if not dead:
        return []

    return [
        Insight(
            key=f"stuck:{row.id}",
            severity=Severity.URGENT,
            title=f"A message from {row.name or row.handle} was never processed",
            detail=(
                f'"{row.body[:120]}" failed {row.attempts} times: '
                f"{row.last_error[:160]}"
            ),
            link="/activity",
            action="Fix the cause and retry it, or reply by hand.",
        )
        for row in dead
    ]


@register_check("backlog")
async def check_backlog(session: AsyncSession) -> list[Insight]:
    """A queue that has stopped draining.

    Distinguishes "busy" from "stuck" by age rather than depth: 40 messages
    arriving at once is normal after an outage; one message sitting unhandled
    for 20 minutes means the worker is not running.
    """
    oldest = (
        await session.execute(
            select(func.min(InboundMessage.received_at)).where(
                InboundMessage.status.in_(("pending", "processing"))
            )
        )
    ).scalar_one_or_none()
    if oldest is None:
        return []

    waiting = seconds_since(oldest)
    if waiting < 20 * 60:
        return []

    return [
        Insight(
            key="backlog:stalled",
            severity=Severity.URGENT,
            title="ARIA has stopped processing incoming messages",
            detail=(
                f"The oldest unprocessed message has been waiting "
                f"{int(waiting // 60)} minutes. The queue worker may not be "
                "running, or the local model may be down."
            ),
            link="/activity",
            action="Check that the API and Ollama are both running.",
        )
    ]


@register_check("unreviewed_autonomous")
async def check_unreviewed_autonomous(session: AsyncSession) -> list[Insight]:
    """Autonomous replies MORICE has not looked at.

    This exists because of a specific failure mode: ARIA learns most from
    explicit feedback, treats silence as no evidence, and therefore gets
    quietly worse at knowing whether she is doing well the less he reviews.
    Reminding him is how the learning loop stays closed.
    """
    cutoff = _now() - timedelta(hours=24)
    count = (
        await session.execute(
            select(func.count(AutonomousResponse.id)).where(
                AutonomousResponse.user_reaction == "none",
                AutonomousResponse.send_status == "sent",
                AutonomousResponse.created_at < cutoff,
            )
        )
    ).scalar_one() or 0

    if count < 3:
        return []

    return [
        Insight(
            key="autonomous:unreviewed",
            severity=Severity.ATTENTION,
            title=f"{count} autonomous replies are still unreviewed",
            detail=(
                "ARIA does not treat silence as approval, so these taught her "
                "nothing. Reviewing them is what makes her better at speaking "
                "in your voice."
            ),
            link="/activity",
            action="Approve or correct them on the Activity page.",
        )
    ]


@register_check("blocked_sends")
async def check_blocked_sends(session: AsyncSession) -> list[Insight]:
    """Replies ARIA prepared but was refused permission to send.

    Worth surfacing because it usually means a policy is mis-set rather than
    that something dangerous was caught — and a policy nobody notices is
    wrong is a policy that silently makes ARIA useless.
    """
    blocked = list(
        (
            await session.execute(
                select(AutonomousResponse)
                .where(AutonomousResponse.send_status == "blocked")
                .order_by(AutonomousResponse.created_at.desc())
                .limit(5)
            )
        ).scalars()
    )
    if not blocked:
        return []

    return [
        Insight(
            key=f"blocked:{row.id}",
            severity=Severity.ATTENTION,
            title="A reply was blocked at the last moment",
            detail=f'"{row.response[:100]}" — {row.send_error[:160]}',
            link="/activity",
            action="Check whether the policy is what you intended.",
        )
        for row in blocked
    ]


@register_check("stale_drafts")
async def check_stale_drafts(session: AsyncSession) -> list[Insight]:
    """Drafts waiting so long the conversation has moved on.

    A three-day-old draft reply is not useful; sending it would be worse than
    not replying. Better to tell MORICE it has gone stale than to leave it
    looking actionable.
    """
    cutoff = _now() - timedelta(days=2)
    rows = list(
        (
            await session.execute(
                select(MessageDraft, Contact)
                .join(Contact, Contact.id == MessageDraft.contact_id)
                .where(
                    MessageDraft.status == "pending",
                    MessageDraft.created_at < cutoff,
                )
                .order_by(MessageDraft.created_at)
                .limit(5)
            )
        ).all()
    )
    return [
        Insight(
            key=f"stale_draft:{draft.id}",
            severity=Severity.FYI,
            title=f"An unanswered message from {contact.name} is 2+ days old",
            detail=f'They said: "{draft.incoming[:120]}"',
            link="/whatsapp",
            action="Reply, or dismiss the draft — it is probably stale now.",
        )
        for draft, contact in rows
    ]


@register_check("overdue_tasks")
async def check_overdue_tasks(session: AsyncSession) -> list[Insight]:
    """Tasks past their due date.

    One insight for all of them rather than one each: five separate
    notifications about five overdue tasks is how a notification list becomes
    something you scroll past.
    """
    overdue = list(
        (
            await session.execute(
                select(Task)
                .where(Task.status == "open", Task.due_at < _now())
                .order_by(Task.due_at)
                .limit(20)
            )
        ).scalars()
    )
    if not overdue:
        return []

    names = ", ".join(t.title for t in overdue[:3])
    more = f" and {len(overdue) - 3} more" if len(overdue) > 3 else ""
    return [
        Insight(
            key="tasks:overdue",
            severity=Severity.ATTENTION,
            title=f"{len(overdue)} task(s) are overdue",
            detail=f"{names}{more}",
            link="/tasks",
            action="Complete them, or move the dates so they stop nagging.",
        )
    ]


@register_check("pending_approvals")
async def check_pending_approvals(session: AsyncSession) -> list[Insight]:
    """Actions waiting on a human decision.

    These block real work: an approval nobody makes is an email nobody sends.
    """
    cutoff = _now() - timedelta(hours=6)
    count = (
        await session.execute(
            select(func.count(ActionRequest.id)).where(
                ActionRequest.status == "pending",
                ActionRequest.created_at < cutoff,
            )
        )
    ).scalar_one() or 0
    if count == 0:
        return []

    return [
        Insight(
            key="approvals:waiting",
            severity=Severity.ATTENTION,
            title=f"{count} action(s) have been waiting over 6 hours",
            detail="Nothing happens until you approve or reject them.",
            link="/approvals",
            action="Review the approval queue.",
        )
    ]


@register_check("autonomy_drift")
async def check_autonomy_drift(session: AsyncSession) -> list[Insight]:
    """Contacts where ARIA is being corrected often.

    The engine already downgrades these to SUGGEST automatically. This tells
    MORICE it happened, because an automatic withdrawal he never learns about
    looks like ARIA mysteriously going quiet.
    """
    from src.whatsapp import decision

    contacts = list(
        (
            await session.execute(
                select(Contact).where(Contact.autonomy_enabled.is_(True))
            )
        ).scalars()
    )

    insights: list[Insight] = []
    for contact in contacts:
        reviewed, rate = await decision.correction_history(session, contact.id)
        if reviewed >= decision.MIN_RESPONSES_FOR_RATE and rate > decision.MAX_CORRECTION_RATE:
            insights.append(
                Insight(
                    key=f"drift:{contact.id}",
                    severity=Severity.ATTENTION,
                    title=f"ARIA has stopped auto-replying to {contact.name}",
                    detail=(
                        f"You corrected {rate:.0%} of her {reviewed} reviewed "
                        "replies, so she has gone back to suggesting. She will "
                        "not resume on her own."
                    ),
                    link="/activity",
                    action=(
                        "Keep correcting her until the rate drops, or narrow "
                        "what she is allowed to handle for this contact."
                    ),
                )
            )
    return insights


@register_check("upcoming_interviews")
async def check_upcoming_interviews(session: AsyncSession) -> list[Insight]:
    """An interview in the next 48 hours.

    The one career event where a reminder is worth interrupting for, because
    preparation has to happen before it, not after.
    """
    soon = _now() + timedelta(hours=48)
    interviews = list(
        (
            await session.execute(
                select(Task)
                .where(
                    Task.kind == "interview",
                    Task.status == "open",
                    Task.due_at > _now(),
                    Task.due_at < soon,
                )
                .order_by(Task.due_at)
            )
        ).scalars()
    )

    insights: list[Insight] = []
    for interview in interviews:
        hours = int(seconds_until(interview.due_at) // 3600)
        insights.append(
            Insight(
                key=f"interview:{interview.id}",
                severity=Severity.ATTENTION,
                title=f"Interview in {hours} hours: {interview.title}",
                detail="ARIA can prepare likely questions from the job description.",
                link="/jobs",
                action="Run interview prep on the Jobs page.",
            )
        )
    return insights


@register_check("stale_applications")
async def check_stale_applications(session: AsyncSession) -> list[Insight]:
    """Applications sent weeks ago with no movement.

    Grouped into one insight: a separate notification per application would be
    the fastest way to make MORICE stop reading them.
    """
    from src.models import JobApplication

    cutoff = _now() - timedelta(days=21)
    stale = list(
        (
            await session.execute(
                select(JobApplication)
                .where(
                    JobApplication.status == "applied",
                    JobApplication.created_at < cutoff,
                )
                .order_by(JobApplication.created_at)
            )
        ).scalars()
    )
    if not stale:
        return []

    names = ", ".join(f"{a.company} ({a.role})" for a in stale[:3])
    more = f" and {len(stale) - 3} more" if len(stale) > 3 else ""
    return [
        Insight(
            key="jobs:stale",
            severity=Severity.FYI,
            title=f"{len(stale)} application(s) have had no update in 3 weeks",
            detail=f"{names}{more}",
            link="/jobs",
            action="Follow up, or mark them rejected so they stop counting.",
        )
    ]


@register_check("neglected_learning")
async def check_neglected_learning(session: AsyncSession) -> list[Insight]:
    """Something MORICE started learning and stopped.

    Deliberately gentle (FYI) and deliberately one insight for all of them.
    An assistant that nags about self-improvement is one you mute.
    """
    from src.models import LearningTopic

    cutoff = _now() - timedelta(days=30)
    neglected = list(
        (
            await session.execute(
                select(LearningTopic)
                .where(
                    LearningTopic.status == "learning",
                    LearningTopic.created_at < cutoff,
                )
                .order_by(LearningTopic.created_at)
            )
        ).scalars()
    )
    if not neglected:
        return []

    names = ", ".join(t.name for t in neglected[:3])
    return [
        Insight(
            key="learning:neglected",
            severity=Severity.FYI,
            title=f"{len(neglected)} topic(s) have been 'learning' for a month",
            detail=names,
            link="/learning",
            action="Pick one back up, or mark it comfortable if you got there.",
        )
    ]


# --- The engine -----------------------------------------------------------

class ProactiveEngine:
    """Runs the checks and records what is new.

    Note what it does NOT hold: a model router, the gateway, or any send path.
    It observes and reports; acting on what it finds is MORICE's decision,
    routed through the normal autonomy layer. A component that both decides
    what matters and acts on it has no supervision left in it.
    """

    def __init__(self, *, cooldown: timedelta = timedelta(hours=12)):
        # How long before the same insight may be raised again after being
        # dismissed. Without this, dismissing something just means seeing it
        # again on the next run.
        self.cooldown = cooldown

    async def run(self, session: AsyncSession) -> list[InsightRow]:
        """Run every check. Returns the insights that are newly raised."""
        found: list[Insight] = []
        for name, check in _checks.items():
            try:
                found.extend(await check(session))
            except Exception:  # noqa: BLE001 — one broken check must not
                # silence the rest; the check most likely to fail is the one
                # watching whatever is currently broken.
                logger.exception("Proactive check %r failed", name)

        new_rows: list[InsightRow] = []
        for insight in found:
            row = await self._upsert(session, insight)
            if row is not None:
                new_rows.append(row)

        await session.commit()
        if new_rows:
            logger.info("Proactive: %d new insight(s)", len(new_rows))
        return new_rows

    async def _upsert(
        self, session: AsyncSession, insight: Insight
    ) -> InsightRow | None:
        """Store an insight, or stay quiet if it is already known."""
        existing = (
            await session.execute(
                select(InsightRow).where(InsightRow.key == insight.key)
            )
        ).scalar_one_or_none()

        if existing is not None:
            if existing.status == "open":
                # Already raised and not dealt with. Refresh the wording in
                # case the situation changed, but do not re-notify.
                existing.detail = insight.detail
                existing.last_seen_at = _now()
                return None

            dismissed_at = as_utc(existing.dismissed_at or existing.created_at)
            if _now() - dismissed_at < self.cooldown:
                return None  # dismissed recently; respect that

            existing.status = "open"
            existing.detail = insight.detail
            existing.last_seen_at = _now()
            existing.dismissed_at = None
            return existing

        row = InsightRow(
            key=insight.key,
            severity=insight.severity.value,
            title=insight.title,
            detail=insight.detail,
            link=insight.link,
            action=insight.action,
        )
        session.add(row)
        return row


_engine: ProactiveEngine | None = None


def get_engine() -> ProactiveEngine:
    global _engine
    if _engine is None:
        _engine = ProactiveEngine()
    return _engine
