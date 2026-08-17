"""Commands ARIA answers herself, without asking a model.

The directive wants the dashboard to feel like one assistant rather than a
collection of endpoints: "ARIA, briefing", "why did you send that?", "ARIA,
stop autonomous WhatsApp" should reach the capability that owns them instead of
being answered conversationally by a chat model that has no access to any of it.

Three decisions shape this module.

**Matching is deterministic, not model-judged.** A model asked "is this a
command?" is wrong occasionally, and the failure is asymmetric: mistaking a
sentence about stopping procrastination for a kill-switch command, or —
worse — failing to recognise "stop" when he means it. So the patterns are
anchored regular expressions over short utterances, and anything that is not
clearly a command falls through to normal conversation. A false negative costs
him a click; a false positive silently does something he did not ask for.

**Answers come from records, not from prose.** The briefing command returns the
assembled briefing. The explanation command returns the stored decision. If
there is nothing to report, that is what it says.

**Only the safe direction is automatic.** "Stop" is honoured immediately,
because the moment he wants ARIA to stop is the moment nothing should stand
between him and stopping her — and stopping is never the dangerous outcome.
"Resume" is deliberately NOT honoured here: restoring autonomy is a deliberate
act, and it stays a deliberate act. ARIA answers with what to press.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models import AutonomousResponse, Contact

# An optional "ARIA," prefix, and nothing else of substance around the command.
# Requiring the utterance to BE the command — rather than to contain it — is
# what keeps "I really need to stop saying yes to everything" out of the kill
# switch.
_PREFIX = r"(?:\s*(?:hey\s+|ok\s+)?aria[,!.\s]+)?"
_SUFFIX = r"[\s,.!?]*"


def _command(*bodies: str) -> re.Pattern[str]:
    joined = "|".join(bodies)
    return re.compile(rf"^{_PREFIX}(?:{joined}){_SUFFIX}$", re.IGNORECASE)


BRIEFING = _command(
    r"brief(?:ing|\s*me)?",
    r"(?:give|show)\s+me\s+(?:my\s+|the\s+)?brief(?:ing)?",
    r"what(?:'s| is| has)?\s*happened(?:\s+while\s+i\s+was\s+(?:away|out|asleep|gone))?",
    r"what\s+did\s+i\s+miss",
    r"what\s+(?:have\s+you|did\s+you)\s+(?:been\s+)?do(?:ne|ing)?(?:\s+today)?",
    r"catch\s+me\s+up",
)

WHY_SENT = _command(
    r"why\s+did\s+you\s+(?:send|say|reply|write)\s*(?:that|it|this)?",
    r"why\s+that\s+reply",
    r"explain\s+(?:that|the\s+last)\s+(?:reply|message|send)",
)

STOP = _command(
    r"stop",
    r"stop\s+(?:it|now|everything)",
    r"emergency\s+stop",
    r"stop\s+(?:aria|yourself)",
    r"stop\s+(?:replying|sending|answering)(?:\s+to)?(?:\s+whats\s*app)?",
    r"stop\s+autonomous(?:\s+whats\s*app)?(?:\s+(?:replies|sending|messages))?",
    r"stop\s+whats\s*app(?:\s+(?:replies|sending|autonomy))?",
    r"don'?t\s+(?:send|reply)\s+anything(?:\s+else)?",
)

PAUSE = _command(
    r"pause",
    r"pause\s+(?:aria|yourself|everything)",
    r"hold\s+(?:off|on)",
)

RESUME = _command(
    r"resume",
    r"resume\s+(?:aria|yourself|sending|autonomy|autonomous(?:\s+whats\s*app)?)",
    r"(?:start|carry\s+on|continue)\s+(?:replying|sending|again)",
    r"un-?pause",
    r"you\s+can\s+(?:start|reply)\s+again",
)


@dataclass(frozen=True)
class Handled:
    """A command ARIA answered herself."""

    reply: str
    command: str


async def handle(session: AsyncSession, text: str) -> Handled | None:
    """Answer `text` directly, or return None to let the conversation continue."""
    message = text.strip()
    if len(message) > 200:
        # Commands are short. A long message that happens to open with "stop"
        # is a sentence, not an instruction.
        return None

    if BRIEFING.match(message):
        return Handled(await _briefing(session), "briefing")
    if WHY_SENT.match(message):
        return Handled(await _why_sent(session), "explain_send")
    if STOP.match(message):
        return Handled(await _stop(session), "stop")
    if PAUSE.match(message):
        return Handled(await _pause(session), "pause")
    if RESUME.match(message):
        return Handled(_resume_instructions(), "resume_refused")
    return None


async def _briefing(session: AsyncSession) -> str:
    from src.proactive import briefing as briefing_service

    result = await briefing_service.build(session)
    if result.quiet:
        return (
            f"{result.headline}\n\n"
            "No messages, no actions of mine, nothing waiting on you. There are "
            "no records in this period — I am not leaving anything out."
        )

    lines = [result.headline, ""]
    for section in result.sections:
        marker = "!" if section.needs_attention else "-"
        lines.append(f"{marker} {section.heading}: {section.summary}")
        for item in section.items[:4]:
            lines.append(f"    · {item.title}")
            if item.detail:
                lines.append(f"      {item.detail}")
    lines.append("")
    lines.append("Full detail on the dashboard home page.")
    return "\n".join(lines)


async def _why_sent(session: AsyncSession) -> str:
    """Explain the most recent autonomous reply from its stored record.

    Not chain-of-thought — the directive is explicit about that. This is the
    decision as recorded: who, what risk, which policy, how confident, and what
    actually happened to the message.
    """
    row = (
        await session.execute(
            select(AutonomousResponse, Contact)
            .join(Contact, AutonomousResponse.contact_id == Contact.id)
            .order_by(AutonomousResponse.created_at.desc())
            .limit(1)
        )
    ).first()

    if row is None:
        return (
            "I have not replied to anyone on my own yet, so there is nothing to "
            "explain. When I do, this will tell you exactly why."
        )

    response, contact = row
    status = {
        "sent": "It was delivered.",
        "queued": (
            "It has NOT been delivered — it is still in the outbound queue "
            "waiting for the sender device to be linked."
        ),
        "failed": f"Delivery FAILED: {response.send_error or 'no reason recorded'}",
        "blocked": f"It was blocked before sending: {response.send_error}",
    }.get(response.send_status, f"Status: {response.send_status}")

    lines = [
        f'I wrote this to {contact.name}: "{response.response}"',
        "",
        f"In reply to: \"{response.incoming[:200]}\"",
        "",
        "Why I was allowed to:",
        f"  Contact       {contact.name} ({contact.relationship})",
        f"  Autonomy      {response.autonomy_mode or 'unknown'}, enabled for this contact",
        f"  Message type  {response.action_type or 'unclassified'}",
        f"  Risk          {response.risk_level or 'unknown'}"
        + (
            f" ({', '.join(response.risk_categories)})"
            if response.risk_categories
            else ""
        ),
        f"  My confidence {response.communication_confidence:.0%} that I sound like you",
        f"  Written by    {response.model or 'unknown model'}",
        "",
        status,
    ]
    if response.decision_reasons:
        lines.append("")
        lines.append("The deciding factor was: " + response.decision_reasons[0])
    if response.user_reaction == "none":
        lines.append("")
        lines.append(
            "You have not told me whether it was right. If it was not, correct "
            "it on the activity page and I will learn from the difference."
        )
    return "\n".join(lines)


async def _stop(session: AsyncSession) -> str:
    """Press the same kill switch the button presses.

    Deliberately calls the endpoint's own handler rather than setting the flag
    here. A second code path for the emergency stop is a second place for it to
    be subtly wrong, and the existing one already forces observe mode, writes
    the audit event, and cancels what is in flight.
    """
    from src.routers.whatsapp import AutonomyIn, set_autonomy

    state = await set_autonomy(AutonomyIn(emergency_stop=True), session)

    return (
        "Stopped. Emergency stop is on:\n"
        "  - no WhatsApp message can leave, autonomous or approved\n"
        "  - anything already queued is cancelled\n"
        f"  - autonomy is forced to {state.mode}\n\n"
        "I am still receiving and remembering messages — I just cannot act. "
        "Turn this off deliberately from the WhatsApp page; I will not do it "
        "for you on a typed word."
    )


async def _pause(session: AsyncSession) -> str:
    from src.routers.whatsapp import AutonomyIn, set_autonomy

    await set_autonomy(AutonomyIn(paused=True), session)
    return (
        "Paused. I will not send anything or act on my own, and anything queued "
        "is cancelled. Your autonomy settings are untouched, so resuming from "
        "the WhatsApp page puts everything back exactly as it was."
    )


def _resume_instructions() -> str:
    return (
        "I will not start myself again on a typed word — turning me back on "
        "should be something you did on purpose, not something a sentence could "
        "do by accident.\n\n"
        "Open the WhatsApp page and press Resume (or Clear emergency stop). It "
        "restores the mode you had before, so there is nothing to reconfigure."
    )
