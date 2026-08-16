"""The background scheduler — ARIA's only source of unprompted activity.

Redis has been running unused since Phase 0, reserved for queues that were
never built, and this is where a Celery-shaped solution would normally get
added. It is not needed: ARIA is one process serving one person, and the work
is "run seven database queries every few minutes". An asyncio task does that
exactly as well, with no broker, no worker process, and nothing new to keep
alive.

If ARIA ever needs work distributed across machines, this is the thing to
replace. Until then, replacing it would be adding infrastructure to serve an
architecture that does not exist.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

logger = logging.getLogger(__name__)


class Scheduler:
    """Runs one coroutine on an interval, surviving its own failures.

    The loop must outlive any single failed run: the moment something breaks
    is exactly when MORICE most needs the checks that notice breakage.
    """

    def __init__(self, run_once, *, interval_seconds: float, name: str = "scheduler"):
        self._run_once = run_once
        self.interval = interval_seconds
        self.name = name
        self._task: asyncio.Task | None = None
        self._stopping = asyncio.Event()
        self.last_run_at: datetime | None = None
        self.last_error: str = ""
        self.runs = 0

    def start(self) -> None:
        if self._task is None or self._task.done():
            self._stopping.clear()
            self._task = asyncio.create_task(self._loop(), name=self.name)
            logger.info("%s started (every %ss)", self.name, self.interval)

    async def stop(self) -> None:
        self._stopping.set()
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass
            self._task = None
            logger.info("%s stopped", self.name)

    @property
    def running(self) -> bool:
        return self._task is not None and not self._task.done()

    async def _loop(self) -> None:
        # Wait one interval before the first run so a restart loop cannot
        # hammer the checks, and so startup stays fast.
        while not self._stopping.is_set():
            try:
                await asyncio.wait_for(self._stopping.wait(), timeout=self.interval)
                return  # stop requested
            except TimeoutError:
                pass

            try:
                await self._run_once()
                self.last_error = ""
            except Exception as exc:  # noqa: BLE001 — the loop must survive
                self.last_error = f"{type(exc).__name__}: {exc}"
                logger.exception("%s run failed", self.name)
            finally:
                self.runs += 1
                self.last_run_at = datetime.now(timezone.utc)


_scheduler: Scheduler | None = None


async def _run_checks() -> None:
    from src.db import SessionMaker
    from src.proactive import get_engine

    async with SessionMaker() as session:
        await get_engine().run(session)


def start_scheduler(*, interval_seconds: float = 300.0) -> None:
    """Start the proactive loop. Idempotent."""
    global _scheduler
    if _scheduler is None:
        _scheduler = Scheduler(
            _run_checks, interval_seconds=interval_seconds, name="proactive"
        )
    _scheduler.start()


async def stop_scheduler() -> None:
    global _scheduler
    if _scheduler is not None:
        await _scheduler.stop()
        _scheduler = None


def scheduler_status() -> dict:
    """Exposed so a scheduler that has quietly died is visible.

    A background loop nobody can see the state of is a background loop that
    stops working without anyone noticing.
    """
    if _scheduler is None:
        return {"running": False, "runs": 0, "last_run_at": None, "last_error": ""}
    return {
        "running": _scheduler.running,
        "runs": _scheduler.runs,
        "last_run_at": _scheduler.last_run_at,
        "last_error": _scheduler.last_error,
        "interval_seconds": _scheduler.interval,
    }
