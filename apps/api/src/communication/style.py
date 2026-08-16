"""Style analysis — measurable facts about how MORICE writes.

Everything here is COMPUTED from real messages. Nothing is estimated by a
model and nothing is invented: if the profile says "average 12 words over 37
messages", both numbers are counted from his actual text.

That matters because the product vision forbids fabricated statistics, and
because a number you can recompute is a number you can trust.

Pure functions, no I/O — so the whole analysis layer is testable without a
database or a model.
"""

from __future__ import annotations

import re
import unicodedata
from collections import Counter
from dataclasses import dataclass, field

# Emoji live in these Unicode categories/ranges; good enough for rate counting.
_EMOJI_PATTERN = re.compile(
    "[" "\U0001f300-\U0001faff" "\U00002600-\U000027bf" "\U0001f1e6-\U0001f1ff" "]"
)

_WORD = re.compile(r"[^\W\d_]+", re.UNICODE)

# Common Kiswahili markers. Used only to detect language mix, never to
# translate — a word list is not a language model.
_SWAHILI_MARKERS = {
    "habari", "asante", "sawa", "karibu", "pole", "ndiyo", "hapana", "tafadhali",
    "rafiki", "mambo", "poa", "nzuri", "bwana", "dada", "kaka", "leo", "kesho",
    "sasa", "naomba", "nini", "wapi", "vipi", "shida", "haraka", "tutaonana",
}

# Openers we recognise as greetings when a message starts with one.
_GREETING_WORDS = {
    "hi", "hey", "hello", "yo", "morning", "afternoon", "evening", "dear",
    "habari", "mambo", "sasa", "vipi", "karibu", "greetings", "hii",
}

# Closers we recognise as sign-offs at the end of a message.
_SIGNOFF_WORDS = {
    "thanks", "thank", "regards", "cheers", "best", "sincerely", "later",
    "bye", "asante", "sawa", "tutaonana", "peace", "ttyl",
}


@dataclass
class StyleMetrics:
    """Measured writing characteristics, with the evidence behind them."""

    sample_size: int = 0
    avg_words: float = 0.0
    avg_sentences: float = 0.0
    emoji_rate: float = 0.0          # fraction of messages containing emoji
    question_rate: float = 0.0
    exclamation_rate: float = 0.0
    lowercase_start_rate: float = 0.0  # informality signal
    ellipsis_rate: float = 0.0
    greetings: list[tuple[str, int]] = field(default_factory=list)
    signoffs: list[tuple[str, int]] = field(default_factory=list)
    common_phrases: list[tuple[str, int]] = field(default_factory=list)
    swahili_rate: float = 0.0        # fraction of messages with Kiswahili
    mixed_language_rate: float = 0.0  # both languages in one message

    def as_dimensions(self) -> dict[str, str]:
        """Flatten into storable dimension -> human-readable value pairs."""
        dims: dict[str, str] = {
            "avg_words": f"{self.avg_words:.1f} words per message",
            "avg_sentences": f"{self.avg_sentences:.1f} sentences per message",
            "emoji_rate": _rate_phrase(self.emoji_rate, "uses emoji"),
            "question_rate": _rate_phrase(self.question_rate, "asks a question"),
            "exclamation_rate": _rate_phrase(self.exclamation_rate, "uses '!'"),
            "capitalisation": (
                _rate_phrase(self.lowercase_start_rate, "starts lowercase")
            ),
            "language": _language_phrase(self.swahili_rate, self.mixed_language_rate),
        }
        if self.greetings:
            dims["greeting"] = ", ".join(f"{g!r} ({n}x)" for g, n in self.greetings[:3])
        if self.signoffs:
            dims["signoff"] = ", ".join(f"{s!r} ({n}x)" for s, n in self.signoffs[:3])
        if self.common_phrases:
            dims["common_phrases"] = ", ".join(
                f"{p!r} ({n}x)" for p, n in self.common_phrases[:5]
            )
        return dims


def _rate_phrase(rate: float, label: str) -> str:
    pct = round(rate * 100)
    if pct == 0:
        return f"never {label}"
    if pct >= 80:
        return f"almost always {label} ({pct}%)"
    if pct >= 40:
        return f"often {label} ({pct}%)"
    return f"sometimes {label} ({pct}%)"


def _language_phrase(swahili: float, mixed: float) -> str:
    if swahili == 0:
        return "writes in English"
    if mixed >= 0.2:
        return (
            f"mixes English and Kiswahili ({round(mixed * 100)}% of messages "
            "contain both)"
        )
    return f"uses Kiswahili in {round(swahili * 100)}% of messages"


def _words(text: str) -> list[str]:
    return _WORD.findall(text.lower())


def _has_emoji(text: str) -> bool:
    if _EMOJI_PATTERN.search(text):
        return True
    # Catch symbols the range misses (e.g. some dingbats).
    return any(unicodedata.category(ch) == "So" for ch in text)


def _sentence_count(text: str) -> int:
    parts = [p for p in re.split(r"[.!?]+", text) if p.strip()]
    return max(1, len(parts))


def analyze(messages: list[str]) -> StyleMetrics:
    """Measure writing style across a set of MORICE's own messages.

    Returns zeroed metrics for an empty input rather than guessing — an
    unknown style must look unknown, not average.
    """
    texts = [m.strip() for m in messages if m and m.strip()]
    if not texts:
        return StyleMetrics()

    n = len(texts)
    total_words = 0
    total_sentences = 0
    emoji_msgs = question_msgs = excl_msgs = lower_msgs = ellipsis_msgs = 0
    swahili_msgs = mixed_msgs = 0
    greetings: Counter[str] = Counter()
    signoffs: Counter[str] = Counter()
    phrases: Counter[str] = Counter()

    for text in texts:
        words = _words(text)
        total_words += len(words)
        total_sentences += _sentence_count(text)

        if _has_emoji(text):
            emoji_msgs += 1
        if "?" in text:
            question_msgs += 1
        if "!" in text:
            excl_msgs += 1
        if "..." in text or "…" in text:
            ellipsis_msgs += 1
        first_alpha = next((c for c in text if c.isalpha()), "")
        if first_alpha and first_alpha.islower():
            lower_msgs += 1

        sw = sum(1 for w in words if w in _SWAHILI_MARKERS)
        if sw:
            swahili_msgs += 1
            # "Mixed" means Kiswahili markers alongside mostly-other words.
            if len(words) - sw >= 2:
                mixed_msgs += 1

        if words:
            if words[0] in _GREETING_WORDS:
                greetings[words[0]] += 1
            if words[-1] in _SIGNOFF_WORDS:
                signoffs[words[-1]] += 1

        # Recurring 2-3 word phrases: his verbal habits ("just checking",
        # "let me know"). Only phrases seen more than once survive later.
        for size in (2, 3):
            for i in range(len(words) - size + 1):
                phrases[" ".join(words[i : i + size])] += 1

    # A phrase is only a habit if it recurs; drop one-offs to avoid overfitting.
    repeated = [(p, c) for p, c in phrases.most_common(40) if c >= 2]

    return StyleMetrics(
        sample_size=n,
        avg_words=total_words / n,
        avg_sentences=total_sentences / n,
        emoji_rate=emoji_msgs / n,
        question_rate=question_msgs / n,
        exclamation_rate=excl_msgs / n,
        lowercase_start_rate=lower_msgs / n,
        ellipsis_rate=ellipsis_msgs / n,
        greetings=greetings.most_common(3),
        signoffs=signoffs.most_common(3),
        common_phrases=repeated[:5],
        swahili_rate=swahili_msgs / n,
        mixed_language_rate=mixed_msgs / n,
    )


def diff_summary(draft: str, final: str) -> list[str]:
    """Describe how MORICE changed ARIA's draft, in learnable terms.

    Not a character diff — the useful signal is directional: shorter/longer,
    more/less formal, emoji added, greeting changed. Those map onto the same
    dimensions the profile stores.
    """
    observations: list[str] = []
    d_words, f_words = _words(draft), _words(final)
    if not d_words and not f_words:
        return observations

    # Length direction (only when the change is meaningful).
    if d_words and f_words:
        ratio = len(f_words) / max(1, len(d_words))
        if ratio <= 0.7:
            observations.append(
                f"prefers shorter: cut {len(d_words)} words to {len(f_words)}"
            )
        elif ratio >= 1.4:
            observations.append(
                f"prefers longer: expanded {len(d_words)} words to {len(f_words)}"
            )

    d_emoji, f_emoji = _has_emoji(draft), _has_emoji(final)
    if f_emoji and not d_emoji:
        observations.append("adds emoji")
    elif d_emoji and not f_emoji:
        observations.append("removes emoji")

    d_open = d_words[0] if d_words else ""
    f_open = f_words[0] if f_words else ""
    if d_open != f_open and (d_open in _GREETING_WORDS or f_open in _GREETING_WORDS):
        observations.append(f"prefers opening {f_open!r} over {d_open!r}")

    d_sw = any(w in _SWAHILI_MARKERS for w in d_words)
    f_sw = any(w in _SWAHILI_MARKERS for w in f_words)
    if f_sw and not d_sw:
        observations.append("adds Kiswahili")
    elif d_sw and not f_sw:
        observations.append("removes Kiswahili")

    if "!" in final and "!" not in draft:
        observations.append("adds exclamation")
    if final.strip() and final.strip()[0].islower() and draft.strip() and draft.strip()[0].isupper():
        observations.append("prefers lowercase opening")

    return observations
