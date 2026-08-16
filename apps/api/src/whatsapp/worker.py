"""Wiring for the background queue drain.

Kept apart from `queue.py` so the queue mechanics stay free of application
dependencies (the model router, the app lifespan) and remain testable on their
own. This module is the only place that knows both halves.
"""

from __future__ import annotations

import logging

from src.whatsapp import pipeline
from src.whatsapp.queue import QueueWorker

logger = logging.getLogger(__name__)

_worker: QueueWorker | None = None


def _make_processor(model_router):
    async def process(session, row) -> str:
        _, outcome = await pipeline.process_inbound(session, model_router, row)
        return outcome

    return process


async def drain_due(session_factory, model_router) -> int:
    """Process every message currently due. Returns how many were handled.

    Used by the recovery endpoint and by tests, which need the queue to drain
    on demand rather than on a timer.
    """
    return await QueueWorker(session_factory, _make_processor(model_router)).drain_once()


def start_worker(session_factory, model_router, *, poll_seconds: float = 2.0) -> None:
    """Start the singleton drain loop. Idempotent."""
    global _worker
    if _worker is None:
        _worker = QueueWorker(
            session_factory, _make_processor(model_router), poll_seconds=poll_seconds
        )
    _worker.start()


async def stop_worker() -> None:
    global _worker
    if _worker is not None:
        await _worker.stop()
        _worker = None
