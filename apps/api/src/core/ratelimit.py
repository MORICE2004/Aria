"""Rate limiting and login lockout.

In-process and in-memory on purpose. ARIA is a single-user system on one
machine; a Redis-backed distributed limiter would be infrastructure serving an
architecture that does not exist. The tradeoff is stated plainly: counters
reset when the API restarts, so this stops password guessing and runaway
clients, not a determined attacker who can also restart the process. Someone
who can restart ARIA's process has already won.

Two mechanisms, because they answer different questions:

  * `RateLimiter`  — "is this caller making too many requests?" Sliding window.
  * `Lockout`      — "has this caller failed to log in too many times?" A
                     failed login is not merely traffic; it is evidence.
"""

from __future__ import annotations

import time
from collections import defaultdict, deque
from dataclasses import dataclass, field


class RateLimiter:
    """Sliding-window request limiter, keyed by caller.

    A sliding window rather than a fixed one: fixed windows let a caller send
    the full quota at 0:59 and again at 1:01, which is exactly the burst the
    limit exists to prevent.
    """

    def __init__(self, *, limit: int, window_seconds: float):
        self.limit = limit
        self.window = window_seconds
        self._hits: dict[str, deque[float]] = defaultdict(deque)

    def check(self, key: str) -> tuple[bool, float]:
        """Record an attempt. Returns (allowed, seconds_until_retry)."""
        now = time.monotonic()
        hits = self._hits[key]
        cutoff = now - self.window
        while hits and hits[0] < cutoff:
            hits.popleft()

        if len(hits) >= self.limit:
            return False, round(hits[0] + self.window - now, 1)

        hits.append(now)
        return True, 0.0

    def reset(self, key: str) -> None:
        self._hits.pop(key, None)


@dataclass
class _Attempts:
    count: int = 0
    locked_until: float = 0.0
    history: list[float] = field(default_factory=list)


class Lockout:
    """Progressive lockout after repeated login failures.

    The delay grows with each lockout rather than resetting, so a patient
    attacker gains nothing by waiting out a fixed penalty. MORICE, who knows
    his own password, will essentially never see this.
    """

    def __init__(self, *, threshold: int = 5, base_seconds: float = 60.0):
        self.threshold = threshold
        self.base = base_seconds
        self._state: dict[str, _Attempts] = defaultdict(_Attempts)

    def locked_for(self, key: str) -> float:
        """Seconds remaining on a lock, or 0 if not locked."""
        state = self._state[key]
        remaining = state.locked_until - time.monotonic()
        return round(remaining, 1) if remaining > 0 else 0.0

    def record_failure(self, key: str) -> float:
        """Count a failed attempt. Returns seconds locked out (0 if not yet)."""
        state = self._state[key]
        state.count += 1
        if state.count < self.threshold:
            return 0.0

        # Each additional lockout doubles, capped at an hour. Long enough to
        # make guessing pointless, short enough that a mistyped password does
        # not lock MORICE out of his own assistant for the evening.
        lockouts = state.count - self.threshold + 1
        penalty = min(self.base * (2 ** (lockouts - 1)), 3600.0)
        state.locked_until = time.monotonic() + penalty
        return penalty

    def record_success(self, key: str) -> None:
        """A correct password clears the record entirely."""
        self._state.pop(key, None)


# Shared instances. Login is deliberately much tighter than general traffic:
# the dashboard polls several endpoints every few seconds, while nobody needs
# to attempt a password ten times a minute.
login_limiter = RateLimiter(limit=10, window_seconds=60)
login_lockout = Lockout(threshold=5, base_seconds=60)

# Generous, because the activity dashboard refreshes on a timer and a limit
# that fights the UI would just get raised until it meant nothing.
api_limiter = RateLimiter(limit=600, window_seconds=60)

# The bridge delivers a spooled backlog in a burst after an outage, so its
# limit must comfortably exceed a realistic flood. Set well above what a
# person could ever receive, while still bounding a runaway loop.
ingest_limiter = RateLimiter(limit=300, window_seconds=60)


def client_key(request) -> str:
    """Identify the caller for limiting purposes.

    Uses the socket address only. Forwarded headers are deliberately ignored:
    they are attacker-controlled, and trusting them would let anyone reset
    their own limit by inventing an X-Forwarded-For. If ARIA is ever put
    behind a real reverse proxy, this needs revisiting with an explicit list
    of trusted proxies.
    """
    return request.client.host if request.client else "unknown"
