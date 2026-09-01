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

There are two families here. The first is the control commands: short, no
argument, answered from records at no cost. The second carries a subject --
"remember this: ...", "what do you remember about X", "research X", "forget
that" -- and each reaches the capability that owns it. Those cost what that
capability costs, which for research is a model call; routing it there instead
of letting a chat model answer from nothing is the entire point.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.clock import seconds_since
from src.models import AutonomousResponse, Contact, MemoryItem

if TYPE_CHECKING:  # only the type checker needs this; keeps imports acyclic
    from src.memory.service import MemoryService

logger = logging.getLogger(__name__)

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


# ---------- commands that carry a subject ----------
#
# These differ from the control commands above in two ways: they capture what
# they apply to, and they are NOT length-limited. "Remember this: <three
# paragraphs>" is the ordinary shape of a remember command, and the
# 200-character rule that protects the kill switch would throw the content
# away.
#
# The false-positive risk is different in kind, which is why the looser rule is
# defensible. Mistaking a sentence for "remember" writes a row MORICE can see
# on the memory page and delete in one click. Mistaking one for "stop" silently
# disarms ARIA. The exception is forgetting, which destroys data, and is
# therefore the most conservative command in this module.

MAX_BARE_COMMAND_LEN = 200
MAX_SUBJECT_COMMAND_LEN = 8_000

# Written on memories created by the remember command, so "forget that" can
# find its own work and nothing else. A memory extracted from a CV or from a
# WhatsApp message is not something a typed word may delete.
CHAT_MEMORY_PROVENANCE = "You told me to remember this in chat"

# "Forget it" is an ordinary English phrase. It only presses this button when
# ARIA has just stored something from chat, which is when it is nearly certain
# to mean the memory rather than the mood.
FORGET_LAST_WINDOW_SECONDS = 15 * 60

# The relevance floor the chat endpoint already uses for retrieval. Below it,
# hits are noise, and listing them would look like knowledge ARIA does not have.
RELEVANT_SCORE = 0.55


def _subject_command(*bodies: str) -> re.Pattern[str]:
    """The verb, a separator, then the thing the verb applies to.

    The separator is required rather than optional: without it, `remember`
    would match the first eight letters of `remembering` and capture "ing".
    DOTALL, so a multi-paragraph memory survives intact.
    """
    joined = "|".join(bodies)
    return re.compile(
        rf"^{_PREFIX}(?:{joined})(?:\s*[:,-]\s*|\s+)(?P<subject>\S.*?){_SUFFIX}$",
        re.IGNORECASE | re.DOTALL,
    )


REMEMBER = _subject_command(
    r"remember(?:\s+(?:this|that|the\s+following))?",
    r"(?:make\s+a\s+|take\s+a\s+)?note(?:\s+(?:this|that|down))?",
    r"keep\s+in\s+mind(?:\s+that)?",
    r"don'?t\s+forget(?:\s+that)?",
    r"save\s+(?:this|that)(?:\s+to\s+memory)?",
)

RECALL = _subject_command(
    r"what\s+do\s+you\s+(?:remember|know)\s+(?:about|of|regarding)",
    r"what\s+have\s+i\s+told\s+you\s+about",
    r"do\s+you\s+(?:remember|know)(?:\s+anything)?(?:\s+about)?",
    r"recall",
)

RESEARCH = _subject_command(
    r"research",
    r"look\s+into",
    r"dig\s+into",
    r"find\s+out\s+(?:about|what\s+you\s+(?:have|know)\s+about)",
    r"what\s+do\s+you\s+have\s+on",
)

FORGET_LAST = _command(
    r"forget\s+(?:that|it|this)",
    r"forget\s+the\s+last\s+(?:one|thing|note|memory)",
    r"(?:undo|scratch|cancel)\s+(?:that|it|this)",
    r"never\s*mind\s+that",
)

FORGET_SUBJECT = _subject_command(
    r"forget\s+(?:everything\s+)?(?:about)?",
    r"delete\s+what\s+you\s+know\s+about",
    r"(?:delete|remove)\s+(?:the\s+)?memor(?:y|ies)\s+(?:about|of)",
)

# "Remember what I told you about the visa?" is a question, not an instruction
# to store the sentence. An interrogative subject plus a question mark is the
# reliable signal, and it costs one check.
_INTERROGATIVE = re.compile(
    r"^(?:what|when|where|who|whom|which|why|how|if|whether)\b", re.IGNORECASE
)


@dataclass(frozen=True)
class Handled:
    """A command ARIA answered herself."""

    reply: str
    command: str


async def handle(
    session: AsyncSession,
    text: str,
    *,
    memory: "MemoryService | None" = None,
    model_router=None,
) -> Handled | None:
    """Answer `text` directly, or return None to let the conversation continue.

    `memory` and `model_router` are optional. A caller without them loses the
    commands that need them and nothing else: a handler missing a dependency
    falls through to the model, which is the same outcome as not recognising
    the command in the first place.
    """
    message = text.strip()

    # Subject-carrying commands go first, and skip the length rule below,
    # because the thing they carry is allowed to be long.
    if len(message) <= MAX_SUBJECT_COMMAND_LEN:
        carried = await _handle_subject_command(session, message, memory, model_router)
        if carried is not None:
            return carried

    if len(message) > MAX_BARE_COMMAND_LEN:
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


# ---------- subject-carrying handlers ----------


async def _handle_subject_command(
    session: AsyncSession,
    message: str,
    memory: MemoryService | None,
    model_router,
) -> Handled | None:
    """Dispatch the commands that carry a subject, most specific first.

    Order matters in one place: "forget that" also matches FORGET_SUBJECT with
    the subject "that", so the no-argument form is checked first or it would
    never be reached.
    """
    if memory is None:
        # Every command below needs the memory service. Without it there is
        # nothing to dispatch to, and falling through to the model is a better
        # answer than an error.
        return None

    if FORGET_LAST.match(message):
        return await _forget_last(session)

    subject = _subject(FORGET_SUBJECT, message)
    if subject:
        return Handled(
            await _forget_subject(session, memory, subject), "forget_subject"
        )

    subject = _subject(RECALL, message)
    if subject:
        return Handled(await _recall(session, memory, subject), "recall")

    subject = _subject(RESEARCH, message)
    if subject:
        if model_router is None:
            return None
        return Handled(
            await _research(session, memory, model_router, subject), "research"
        )

    subject = _subject(REMEMBER, message)
    if subject:
        if message.rstrip().endswith("?") and _INTERROGATIVE.match(subject):
            return None  # a question about a memory, not an instruction to store one
        return Handled(await _remember(session, memory, subject), "remember")

    return None


# A subject that is only a pointing word is not a subject. "Remember that"
# matches REMEMBER twice over — the optional "that" in the verb, or "that" as
# the thing to remember — and the second reading stored a memory whose entire
# content was the word "that".
_EMPTY_SUBJECTS = frozenset(
    {"that", "this", "it", "them", "those", "these", "the following"}
)


def _subject(pattern: re.Pattern[str], message: str) -> str | None:
    """The subject `pattern` captured, or None if there is nothing usable.

    Two ways to have nothing: no letter or digit at all, or nothing but a
    pointing word. Both happen for real — the chat page's suggestion buttons
    fill the box with "remember that " for him to complete, and sending it
    unfinished should reach the model rather than store punctuation.
    """
    match = pattern.match(message)
    if match is None:
        return None
    subject = match["subject"].strip()
    if not any(character.isalnum() for character in subject):
        return None
    if subject.rstrip(".,:;!?").casefold() in _EMPTY_SUBJECTS:
        return None
    return subject


async def _remember(
    session: AsyncSession, memory: MemoryService, subject: str
) -> str:
    """Store what he just said, and report what governance decided about it.

    `explicit=True` because he asked for it in as many words. That overrides
    every importance heuristic: ARIA does not get to decide that something
    MORICE told her to remember was not worth remembering.
    """
    content = subject.strip()
    # The title column is 200 characters and the first line is what he would
    # recognise it by on the memory page.
    title = content.splitlines()[0].strip()[:150] or "Note"

    item = await memory.ingest(
        session,
        title=title,
        content=content,
        kind="note",
        explicit=True,
        provenance=CHAT_MEMORY_PROVENANCE,
    )
    logger.info("Remembered %r from chat (%s)", title, item.memory_type)

    lines = [
        f"Remembered: {title}",
        "",
        f"  Type        {item.memory_type}",
        f"  Importance  {item.importance:.0%}",
    ]
    if item.expires_at is not None:
        lines.append(
            f"  Expires     {item.expires_at:%d %b %Y} "
            "— transient by type; nothing is deleted without you"
        )
    lines.append("")
    lines.append(
        'Say "forget that" if I misread you, or delete it any time from the '
        "memory page."
    )
    return "\n".join(lines)


async def _recall(session: AsyncSession, memory: MemoryService, subject: str) -> str:
    """Answer from memory alone — no model, so nothing can be embellished."""
    query = subject.strip()
    hits = await memory.search(session, query, k=8)
    relevant = [hit for hit in hits if hit.score >= RELEVANT_SCORE]

    if not relevant:
        return (
            f"Nothing on \"{query[:120]}\".\n\n"
            "I searched everything I have stored and found no close match. "
            'If I should know it, tell me: "remember that ...".'
        )

    # One entry per memory item: several chunks of the same note is one thing
    # ARIA remembers, not three.
    seen: dict[str, object] = {}
    for hit in relevant:
        if hit.item_id not in seen:
            seen[hit.item_id] = hit

    lines = [f'What I have on "{query[:120]}":', ""]
    for hit in list(seen.values())[:5]:
        excerpt = " ".join(hit.content.split())
        if len(excerpt) > 260:
            excerpt = excerpt[:257] + "..."
        lines.append(f"- {hit.title}  ({hit.kind}, {hit.score:.0%} match)")
        lines.append(f"    {excerpt}")
    lines.append("")
    lines.append(
        "That is everything above a close-match threshold. Weaker matches are "
        "left out rather than presented as things I know."
    )
    return "\n".join(lines)


async def _forget_last(session: AsyncSession) -> Handled | None:
    """Undo the last thing ARIA was told to remember in chat.

    Returns None — falls through to the model — when there is nothing recent
    to undo, because "forget it" is far more often a mood than an instruction.
    Deliberately scoped to memories this module created: a fact extracted from
    his CV or a WhatsApp message is not something a typed word may delete.
    """
    item = (
        await session.execute(
            select(MemoryItem)
            .where(MemoryItem.provenance == CHAT_MEMORY_PROVENANCE)
            .order_by(MemoryItem.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()

    if item is None:
        return None
    if seconds_since(item.created_at) > FORGET_LAST_WINDOW_SECONDS:
        return None

    title = item.title
    excerpt = " ".join(item.content.split())[:200]
    await session.delete(item)
    await session.commit()
    logger.info("Forgot %r on request", title)

    return Handled(
        f"Forgotten: {title}\n\n"
        f'It said: "{excerpt}"\n\n'
        "Deleted along with its search index. I only undo what you asked me to "
        "remember here — anything I learned from your documents or messages "
        "stays until you delete it on the memory page.",
        "forget_last",
    )


async def _forget_subject(
    session: AsyncSession, memory: MemoryService, subject: str
) -> str:
    """Show what would be deleted. Never delete it.

    The same reasoning as refusing "resume": the destructive direction stays a
    deliberate act. Semantic search is approximate, so a typed phrase deleting
    whatever it happened to match is a way to lose the wrong memory silently.
    """
    query = subject.strip()
    hits = await memory.search(session, query, k=8)
    relevant = [hit for hit in hits if hit.score >= RELEVANT_SCORE]

    if not relevant:
        return (
            f"I have nothing matching \"{query[:120]}\", so there is nothing "
            "to forget."
        )

    seen: dict[str, object] = {}
    for hit in relevant:
        if hit.item_id not in seen:
            seen[hit.item_id] = hit

    lines = [
        "I will not delete memories on a typed phrase — I match by meaning, "
        "not by exact words, so I could take the wrong one and you would never "
        "know which.",
        "",
        f'These are what "{query[:120]}" matches:',
        "",
    ]
    for hit in list(seen.values())[:5]:
        lines.append(f"- {hit.title}  ({hit.kind}, {hit.score:.0%} match)")
    lines.append("")
    lines.append(
        "Open the memory page and delete the ones you mean; deletion there is "
        "immediate and permanent."
    )
    return "\n".join(lines)


async def _research(
    session: AsyncSession,
    memory: MemoryService,
    model_router,
    subject: str,
) -> str:
    """Run the research agent rather than letting a chat model improvise.

    This is the one command that costs money and time, and it is worth both:
    the alternative is a model answering a research question from training
    data while sounding like it looked something up. Every line here points at
    something ARIA actually holds, and the scope note says what she cannot
    reach.
    """
    from src.llm.router import TaskClass
    from src.research import get_research_agent

    question = subject.strip()
    agent = get_research_agent(memory)
    routed = model_router.resolve(TaskClass.REASON, session)
    report = await agent.research(session, routed.provider, question, depth=2)

    lines = [f"Research: {question[:200]}", "", report.answer]

    if report.evidence:
        # Numbered, and NOT de-duplicated, because the answer cites evidence by
        # position: [2] means the second thing gathered. Collapsing repeats
        # would renumber the list and quietly point every citation at the wrong
        # source. The list is what was searched, not a claim that all of it was
        # used — the numbers in the answer say which of it was.
        lines.append("")
        lines.append("Sources, numbered as the answer cites them:")
        for index, finding in enumerate(report.evidence[:8], start=1):
            lines.append(f"  [{index}] {finding.citation}")
        if len(report.evidence) > 8:
            lines.append(f"  ... and {len(report.evidence) - 8} more searched")

    lines.append("")
    lines.append(report.scope_note)
    lines.append("")
    lines.append(
        "Nothing was stored. Use the research page if you want this kept, "
        "with its sources attached."
    )
    return "\n".join(lines)
