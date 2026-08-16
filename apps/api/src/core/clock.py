"""Timezone helpers.

ARIA stores every timestamp as timezone-aware UTC, but SQLite — used by the
whole test suite — has no timezone type and hands back naive datetimes.
Subtracting a naive datetime from an aware one raises, so any arithmetic on a
value that came back from the database is a latent crash that Postgres hides
and SQLite exposes (or the reverse, depending on which one you tested on).

This bit three separate places before it earned a helper: queue backlog
statistics, proactive insight cooldowns, and the interview countdown. A bug
that recurs is a missing abstraction, so here it is.

Rule: any datetime that came out of the database goes through `as_utc()`
before it is compared to or subtracted from another datetime.
"""

from __future__ import annotations

from datetime import datetime, timezone


def now() -> datetime:
    """Timezone-aware UTC now."""
    return datetime.now(timezone.utc)


def as_utc(value: datetime | None) -> datetime | None:
    """Force a datetime to be timezone-aware UTC.

    A naive value is ASSUMED to be UTC rather than local, because that is what
    ARIA always writes. Assuming local time here would silently shift every
    stored timestamp by the machine's offset — which, in Tanzania, is three
    hours, and is exactly the kind of error that looks like a plausible result.
    """
    if value is None:
        return None
    return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)


def seconds_since(value: datetime | None) -> float:
    """How long ago, in seconds. Zero for None."""
    aware = as_utc(value)
    return 0.0 if aware is None else (now() - aware).total_seconds()


def seconds_until(value: datetime | None) -> float:
    """How long from now, in seconds. Negative if past, zero for None."""
    aware = as_utc(value)
    return 0.0 if aware is None else (aware - now()).total_seconds()
