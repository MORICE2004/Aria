"""Parsing WhatsApp chat exports.

WhatsApp's "Export chat" produces a text file of every message in a
conversation. For ARIA that is the richest possible source of MORICE's real
writing voice — thousands of messages he actually sent, rather than the
handful she has happened to observe since the bridge was connected.

Two things this module is careful about:

**Only his side is extracted.** An export contains both halves of a private
conversation. The other person's messages are their voice, not his, and
learning from them would teach ARIA to write like whoever he talks to most.
They are discarded here rather than filtered later, so they never enter the
system at all.

**System noise is not writing.** An export is full of lines that look like
messages and are not: encryption notices, "<Media omitted>", deleted
messages, timer changes. Counting those as style evidence would tell ARIA his
average message is "<Media omitted>", which is both wrong and unfixable-
looking once it is in the profile.

Pure functions, no I/O, so the parsing rules are testable without files.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime

# Android:  "30/06/2025, 11:05 - Sender: message"
# iOS:      "[30/06/2025, 11:05:22] Sender: message"
# Both may use 12-hour clocks with AM/PM, and either / or . as separators.
_LINE = re.compile(
    r"^\[?"
    r"(?P<date>\d{1,4}[/.\-]\d{1,2}[/.\-]\d{2,4})"
    r",\s*"
    r"(?P<time>\d{1,2}:\d{2}(?::\d{2})?)"
    r"\s*(?P<meridiem>[APap]\.?[Mm]\.?)?"
    r"\]?\s*-?\s*"
    r"(?P<rest>.*)$"
)

# A message line is "Sender: text". A system line has no sender, so the colon
# split is what separates the two.
_SENDER = re.compile(r"^(?P<sender>[^:]{1,60}):\s?(?P<body>.*)$", re.DOTALL)

# Placeholders WhatsApp writes in place of content. None of these are writing.
_PLACEHOLDERS = {
    "<media omitted>",
    "<attached: >",
    "this message was deleted",
    "you deleted this message",
    "waiting for this message",
    "waiting for this message. this may take a while.",
    "missed voice call",
    "missed video call",
    "null",
    "(file attached)",
}

# Substrings that mark a line as a WhatsApp notice rather than a message.
_SYSTEM_MARKERS = (
    "messages and calls are end-to-end encrypted",
    "the message timer was updated",
    "you blocked this contact",
    "you unblocked this contact",
    "changed the subject",
    "changed this group's icon",
    "created group",
    "added you",
    "security code changed",
    "disappearing messages were turned",
    "your security code with",
)

# Longer than this and it is a forward, a pasted article, or a shared block —
# not an example of how he writes a message.
MAX_SAMPLE_CHARS = 400


@dataclass(frozen=True)
class ExportedMessage:
    sent_at: datetime | None
    sender: str
    body: str


def parse_export(text: str) -> list[ExportedMessage]:
    """Turn an export into messages, joining multi-line ones.

    A message containing newlines continues on lines that do NOT start with a
    timestamp. Treating those as separate messages would chop his longer
    messages into fragments and skew every length statistic downward.
    """
    messages: list[ExportedMessage] = []
    current: ExportedMessage | None = None

    for raw in text.replace("\r\n", "\n").split("\n"):
        # WhatsApp writes U+200E around some entries; it is invisible and
        # breaks prefix matching.
        line = raw.replace("‎", "").replace("‏", "")

        match = _LINE.match(line)
        if not match:
            if current is not None and line.strip():
                current = ExportedMessage(
                    current.sent_at, current.sender, f"{current.body}\n{line}"
                )
                messages[-1] = current
            continue

        rest = match.group("rest").strip()
        sender_match = _SENDER.match(rest)
        if sender_match is None:
            current = None  # a system notice; nothing to continue
            continue

        current = ExportedMessage(
            sent_at=_parse_timestamp(
                match.group("date"), match.group("time"), match.group("meridiem")
            ),
            sender=sender_match.group("sender").strip(),
            body=sender_match.group("body").strip(),
        )
        messages.append(current)

    return messages


def senders(messages: list[ExportedMessage]) -> dict[str, int]:
    """Message count per sender, most prolific first."""
    counts: dict[str, int] = {}
    for message in messages:
        counts[message.sender] = counts.get(message.sender, 0) + 1
    return dict(sorted(counts.items(), key=lambda kv: -kv[1]))


def is_usable_sample(body: str) -> bool:
    """Is this text actually an example of how someone writes?"""
    stripped = body.strip()
    if not stripped:
        return False
    lowered = stripped.lower()
    if lowered in _PLACEHOLDERS:
        return False
    if any(marker in lowered for marker in _SYSTEM_MARKERS):
        return False
    if stripped.startswith("<") and stripped.endswith(">"):
        return False
    if len(stripped) > MAX_SAMPLE_CHARS:
        return False
    # A bare link is a share, not a sentence.
    if re.fullmatch(r"https?://\S+", stripped):
        return False
    return True


def own_messages(
    messages: list[ExportedMessage], own_sender: str, *, limit: int | None = None
) -> list[str]:
    """The usable messages written by one person, most recent first.

    Recent-first because writing style drifts: how he writes now is a better
    guide than how he wrote two years ago, so a capped import should keep the
    recent end rather than whatever happens to be at the top of the file.
    """
    mine = [
        m.body.strip()
        for m in messages
        if m.sender == own_sender and is_usable_sample(m.body)
    ]
    mine.reverse()  # exports are oldest-first

    if limit is None:
        return mine

    # Deduplicate while preserving order: "ok" sent two hundred times is one
    # piece of evidence about his vocabulary, not two hundred.
    seen: set[str] = set()
    unique: list[str] = []
    for body in mine:
        key = body.lower()
        if key in seen:
            continue
        seen.add(key)
        unique.append(body)
        if len(unique) >= limit:
            break
    return unique


def _parse_timestamp(date: str, time: str, meridiem: str | None) -> datetime | None:
    """Best-effort timestamp. None rather than a guess when ambiguous.

    Day-first is assumed, which is what WhatsApp writes in most locales
    including MORICE's. A wrong guess here costs only ordering, never content,
    so this fails soft.
    """
    normalised = date.replace(".", "/").replace("-", "/")
    clock = time if len(time.split(":")) == 3 else f"{time}:00"
    suffix = ""
    if meridiem:
        clock = f"{clock} {meridiem.replace('.', '').upper()}"
        suffix = " %p"

    for fmt in (f"%d/%m/%Y %H:%M:%S{suffix}", f"%d/%m/%y %H:%M:%S{suffix}",
                f"%Y/%m/%d %H:%M:%S{suffix}", f"%m/%d/%Y %I:%M:%S %p"):
        try:
            return datetime.strptime(f"{normalised} {clock}", fmt)
        except ValueError:
            continue
    return None
