"""Risk classification for inbound messages and proposed replies.

Four levels, and what each one means for autonomy:

    LOW       routine conversation — may be answered automatically, if the
              contact's policy and the autonomy mode both allow it
    MEDIUM    a commitment, a schedule change, professional contact, a
              document — notify or ask, depending on policy
    HIGH      money, employment, legal, sensitive personal, relationship-
              defining, or a promise with material consequences — always ask
    CRITICAL  autonomous execution is refused outright, whatever the mode

Two design decisions worth stating, because both are load-bearing:

**Deterministic rules first, model second.** The rule layer is the floor: a
message containing "send me money" is HIGH before any model has an opinion,
and no model output can lower it. A model can only ever *raise* the level. A
classifier that could be talked down is a classifier an attacker can talk down.

**Risk is assessed on BOTH sides.** The incoming message is scored, and so is
the reply ARIA proposes. A harmless "sure, no problem" is high risk if what it
agrees to is a loan. Scoring only the inbound message would miss exactly the
case that matters — ARIA committing MORICE to something.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum


class RiskLevel(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


_ORDER = [RiskLevel.LOW, RiskLevel.MEDIUM, RiskLevel.HIGH, RiskLevel.CRITICAL]


def rank(level: RiskLevel) -> int:
    return _ORDER.index(level)


def highest(*levels: RiskLevel) -> RiskLevel:
    """The most severe of several assessments. Risk never averages down."""
    return max(levels, key=rank) if levels else RiskLevel.LOW


@dataclass(frozen=True)
class RiskAssessment:
    level: RiskLevel
    # Why, in MORICE's terms. Shown in the dashboard next to every decision;
    # a risk score with no explanation is not auditable.
    reasons: list[str] = field(default_factory=list)
    categories: list[str] = field(default_factory=list)
    # True when the text tries to instruct ARIA rather than talk to MORICE.
    injection_suspected: bool = False

    def merged_with(self, other: "RiskAssessment") -> "RiskAssessment":
        return RiskAssessment(
            level=highest(self.level, other.level),
            reasons=[*self.reasons, *other.reasons],
            categories=sorted({*self.categories, *other.categories}),
            injection_suspected=self.injection_suspected or other.injection_suspected,
        )


# --- Pattern tables -------------------------------------------------------
#
# Kiswahili terms sit alongside English throughout because MORICE's real
# conversations code-switch mid-sentence. An English-only money detector would
# miss "naomba hela" — a genuine money request — and that is precisely the
# message that must never be handled automatically. This was not hypothetical:
# a live Kiswahili money request is already in the message store.

_FINANCIAL = [
    r"\bmoney\b", r"\bcash\b", r"\bloan\b", r"\bpay(ment|ing)?\b",
    r"\blend\b", r"\bborrow\b",
    r"\btransfer\b", r"\binvoice\b", r"\bdeposit\b", r"\brefund\b", r"\bowe\b",
    r"\bdebt\b", r"\bsalary\b", r"\bbank\b", r"\bmpesa\b", r"\bm-pesa\b",
    r"\bpesa\b", r"\bhela\b", r"\bfedha\b", r"\bmkopo\b", r"\bnaomba\b",
    r"\btuma\b", r"\blipa\b", r"\bmalipo\b", r"\bdeni\b",
    r"\$\s?\d", r"\b\d+\s?(usd|eur|tzs|kes|shillings?)\b",
    # "send me 50000" is a money request; a bare "send me the report" is not.
    # Matching the verb alone flagged every document request as financial,
    # which is worse than useless — an over-broad money detector trains
    # MORICE to ignore the one signal that must never be ignored.
    r"\bsend (me )?\d", r"\b(send|tuma)\b.{0,20}\b(money|cash|hela|pesa|fedha)\b",
    r"\b\d{3,}\s?k?\b(?=.*\b(send|lend|borrow|need|naomba|tuma)\b)",
]

_EMPLOYMENT = [
    r"\bjob offer\b", r"\bcontract\b", r"\bresign\b", r"\bnotice period\b",
    r"\bsalary\b", r"\bhir(e|ing)\b", r"\bfired?\b", r"\bterminat(e|ion)\b",
    r"\bemployment\b", r"\binterview\b", r"\bstart date\b", r"\boffer letter\b",
    r"\bkazi\b", r"\bajira\b", r"\bmshahara\b",
]

_LEGAL = [
    r"\blawyer\b", r"\battorney\b", r"\blegal\b", r"\bsue\b", r"\blawsuit\b",
    r"\bcourt\b", r"\bpolice\b", r"\bvisa\b", r"\bimmigration\b", r"\bembassy\b",
    r"\bnda\b", r"\bagreement\b", r"\bsign(ed|ing)?\b", r"\bliabilit(y|ies)\b",
    r"\bmahakama\b", r"\bpolisi\b", r"\bsheria\b",
]

# Credentials get their own tier. Asking for a password, PIN or one-time code
# is never a normal conversational request — there is no autonomy setting under
# which drafting a reply to it is useful, and a plausible-looking draft is
# actively dangerous because it invites a fast approval. So these are CRITICAL
# (blocked outright) rather than HIGH (escalated for approval).
_CREDENTIALS = [
    r"\bpassword\b", r"\bpasswords\b", r"\bpin\b", r"\botp\b",
    r"\bverification code\b", r"\bone.?time code\b", r"\b2fa\b",
    r"\baccount number\b", r"\bcard number\b", r"\bcvv\b", r"\bseed phrase\b",
    r"\bprivate key\b", r"\bnenosiri\b", r"\bnambari ya siri\b",
]

_SENSITIVE_PERSONAL = [
    r"\bid number\b", r"\bpassport\b", r"\bhome address\b", r"\bbirth ?date\b",
    r"\bdate of birth\b", r"\bnida\b",
    r"\bmedical\b", r"\bdiagnos(is|ed)\b", r"\bhospital\b", r"\btherapy\b",
]

_RELATIONSHIP = [
    r"\bi love you\b", r"\bbreak ?up\b", r"\bdivorce\b", r"\bmarriage\b",
    r"\bmarry\b", r"\bare you (mad|angry|upset)\b", r"\bdisappointed\b",
    r"\bwe need to talk\b", r"\bsorry about\b", r"\bfuneral\b", r"\bdied\b",
    r"\bpassed away\b", r"\bhospitali\b", r"\bpole sana\b",
]

_COMMITMENT = [
    r"\bi promise\b", r"\bi'?ll (definitely|certainly|make sure)\b",
    r"\bcount on me\b", r"\bguarantee\b", r"\bcommit\b", r"\bi will pay\b",
    r"\bi agree\b", r"\bdeal\b", r"\bconfirmed?\b", r"\byes,? i (will|can)\b",
    r"\bnakuahidi\b", r"\bnitalipa\b",
]

_SCHEDULING = [
    r"\bmeet(ing)?\b", r"\btomorrow\b", r"\btoday\b", r"\bwhat time\b",
    r"\bsaa ngapi\b", r"\bkesho\b", r"\bleo\b", r"\bschedule\b",
    r"\breschedul(e|ing)\b", r"\bpostpone\b", r"\bcancel\b", r"\bare you coming\b",
    r"\bunakuja\b", r"\btutaonana\b", r"\bavailable\b", r"\bfree (at|on)\b",
]

_DOCUMENTS = [
    r"\bsend (me )?(the )?(cv|resume|document|file|report|pdf)\b",
    r"\battach(ed|ment)\b", r"\bforward (me|the)\b", r"\bshare (the|your)\b",
]

_URGENCY_PRESSURE = [
    r"\burgent(ly)?\b", r"\bright now\b", r"\bimmediately\b", r"\basap\b",
    r"\bemergency\b", r"\bharaka\b", r"\bsasa hivi\b", r"\bdharura\b",
]

# Attempts to treat the message as instructions to ARIA rather than as
# conversation with MORICE. A WhatsApp message is content. Always.
_INJECTION = [
    r"\bignore (all |your |the )?(previous |prior |above )?(instructions?|rules?|prompt)\b",
    r"\bdisregard (your|all|the|previous)\b",
    r"\byou are now\b", r"\bnew instructions?\b", r"\bsystem prompt\b",
    r"\bact as\b", r"\bpretend (to be|you are)\b", r"\bjailbreak\b",
    r"\bdeveloper mode\b", r"\boverride\b", r"\byour (real )?instructions\b",
    r"\brepeat (everything|your prompt|the above)\b",
    # Allows a qualifier chain ("all his contacts", "everything about her
    # details") rather than requiring the noun to follow immediately.
    r"\bsend (me )?(all|everything|his|her|their)\b(\s+\w+){0,3}\s+"
    r"(data|information|info|details|messages|contacts|numbers)\b",
    r"\breveal\b", r"\bprint your\b", r"\bwhat (is|are) your (rules|instructions)\b",
    r"\bpuuza\b",  # Kiswahili: "ignore"
]

_CATEGORY_RULES: list[tuple[str, list[str], RiskLevel, str]] = [
    (
        "credentials",
        _CREDENTIALS,
        RiskLevel.CRITICAL,
        "asks for a password, code or account credential",
    ),
    ("financial", _FINANCIAL, RiskLevel.HIGH, "mentions money or payment"),
    ("employment", _EMPLOYMENT, RiskLevel.HIGH, "concerns employment or a contract"),
    ("legal", _LEGAL, RiskLevel.HIGH, "concerns legal or official matters"),
    (
        "sensitive_personal",
        _SENSITIVE_PERSONAL,
        RiskLevel.HIGH,
        "involves personal or credential data",
    ),
    (
        "relationship",
        _RELATIONSHIP,
        RiskLevel.HIGH,
        "is emotionally or relationally significant",
    ),
    ("commitment", _COMMITMENT, RiskLevel.MEDIUM, "makes or seeks a commitment"),
    ("scheduling", _SCHEDULING, RiskLevel.MEDIUM, "changes or arranges plans"),
    ("documents", _DOCUMENTS, RiskLevel.MEDIUM, "requests a document or file"),
]

_GREETINGS = [
    r"^\s*(hey|hi|hello|yo|sup|habari|mambo|vipi|salama|niaje|shikamoo)\b",
    r"\bhow are you\b", r"\bhabari yako\b", r"\bu ?hali gani\b",
    r"\bgood (morning|afternoon|evening)\b", r"\bwhat'?s up\b",
]


def _matches(patterns: list[str], text: str) -> bool:
    return any(re.search(p, text, flags=re.IGNORECASE) for p in patterns)


def _matched(patterns: list[str], text: str) -> list[str]:
    return [p for p in patterns if re.search(p, text, flags=re.IGNORECASE)]


def detect_injection(text: str) -> bool:
    """Does this text try to give ARIA orders?

    Detection does not change how the message is *handled* as data — it is
    already handled as data everywhere, by construction. What it changes is
    the risk level, so a manipulation attempt never gets an automatic reply
    and always surfaces to MORICE.
    """
    return _matches(_INJECTION, text)


def classify_incoming(text: str, *, relationship: str = "unknown") -> RiskAssessment:
    """Risk of the message ARIA received."""
    reasons: list[str] = []
    categories: list[str] = []
    level = RiskLevel.LOW

    injection = detect_injection(text)
    if injection:
        # CRITICAL, not HIGH: there is no autonomy mode in which ARIA should
        # auto-reply to someone trying to reprogram her. Asking MORICE is the
        # only correct response, and blocking is what forces that.
        level = RiskLevel.CRITICAL
        categories.append("prompt_injection")
        reasons.append(
            "the message contains instructions aimed at ARIA rather than at MORICE"
        )

    for name, patterns, category_level, description in _CATEGORY_RULES:
        if _matches(patterns, text):
            categories.append(name)
            reasons.append(f"{description} ({name})")
            level = highest(level, category_level)

    # Urgency alone is not risk, but urgency ON TOP of money or credentials is
    # the shape of every social-engineering attempt there is.
    if _matches(_URGENCY_PRESSURE, text) and (
        "financial" in categories
        or "sensitive_personal" in categories
        or "credentials" in categories
    ):
        level = RiskLevel.CRITICAL
        reasons.append(
            "urgency combined with a money or credential request — a classic "
            "pressure tactic, so ARIA will not act on it"
        )
        categories.append("pressure")

    # A stranger gets one level of extra caution: ARIA has no history to judge
    # them against, and an unknown number is the likeliest hostile sender.
    if relationship == "unknown" and level is RiskLevel.LOW and not _is_greeting(text):
        level = RiskLevel.MEDIUM
        reasons.append("sender is not a known contact")

    if not reasons:
        reasons.append("routine conversation, no sensitive content detected")

    return RiskAssessment(
        level=level,
        reasons=reasons,
        categories=sorted(set(categories)),
        injection_suspected=injection,
    )


def classify_outgoing(text: str) -> RiskAssessment:
    """Risk of the reply ARIA proposes to send.

    Separate from the inbound assessment because they fail differently. A
    perfectly innocuous question ("can you help me out?") deserves a reply that
    might commit MORICE to something expensive. Scoring only what arrived would
    let that through.
    """
    reasons: list[str] = []
    categories: list[str] = []
    level = RiskLevel.LOW

    for name, patterns, category_level, description in _CATEGORY_RULES:
        if _matches(patterns, text):
            categories.append(name)
            reasons.append(f"the proposed reply {description} ({name})")
            level = highest(level, category_level)

    # A reply that agrees to something is riskier than the topic alone implies.
    if _matches(_COMMITMENT, text):
        level = highest(level, RiskLevel.MEDIUM)

    if not reasons:
        reasons.append("proposed reply is routine")

    return RiskAssessment(
        level=level, reasons=reasons, categories=sorted(set(categories))
    )


def classify_exchange(
    incoming: str, outgoing: str | None = None, *, relationship: str = "unknown"
) -> RiskAssessment:
    """Combined risk of a message and the reply ARIA wants to send.

    The result is the MORE severe of the two, never a blend.
    """
    assessment = classify_incoming(incoming, relationship=relationship)
    if outgoing:
        assessment = assessment.merged_with(classify_outgoing(outgoing))
    return assessment


def _is_greeting(text: str) -> bool:
    return _matches(_GREETINGS, text.strip())


def action_type(text: str) -> str:
    """What kind of exchange this is, in the vocabulary contact policies use.

    Contact permissions are written in these terms ("John may handle greetings
    and scheduling"), so this function and the policy editor must always agree
    on the same names.
    """
    if _matches(_INJECTION, text):
        return "manipulation_attempt"
    if _matches(_CREDENTIALS, text):
        return "sensitive_personal"
    if _matches(_FINANCIAL, text):
        return "financial"
    if _matches(_EMPLOYMENT, text):
        return "employment"
    if _matches(_LEGAL, text):
        return "legal"
    if _matches(_SENSITIVE_PERSONAL, text):
        return "sensitive_personal"
    if _matches(_RELATIONSHIP, text):
        return "relationship"
    if _matches(_DOCUMENTS, text):
        return "documents"
    if _matches(_COMMITMENT, text):
        return "commitment"
    if _matches(_SCHEDULING, text):
        return "scheduling"
    if _is_greeting(text):
        return "greeting"
    return "routine_reply"


# Every action type a contact policy can name. Kept here, next to the
# detector, so the two can never drift apart.
ACTION_TYPES = (
    "greeting",
    "routine_reply",
    "scheduling",
    "status_update",
    "documents",
    "commitment",
    "financial",
    "employment",
    "legal",
    "sensitive_personal",
    "relationship",
    "manipulation_attempt",
)

# What a conservative starting policy permits. Deliberately short: these are
# the categories where a wrong reply costs nothing but a follow-up message.
DEFAULT_ALLOWED_ACTIONS = ("greeting", "routine_reply", "scheduling", "status_update")

# Never autonomous, whatever a policy says. Enforced in the decision engine,
# not merely defaulted here.
NEVER_AUTONOMOUS_ACTIONS = (
    "financial",
    "employment",
    "legal",
    "sensitive_personal",
    "relationship",
    "manipulation_attempt",
)
