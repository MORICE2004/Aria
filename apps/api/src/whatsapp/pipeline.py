"""Processing one queued message — the step between "received" and "handled".

Split out of the ingest endpoint on purpose. Ingest's only responsibility is to
persist the message and return; everything that can fail lives here, behind the
queue's retry and dead-letter machinery.

The same function serves both callers, which is what makes the retry path
trustworthy: the worker does not run a simplified version of what the request
handler does. There is one code path, run twice at most.
"""

from __future__ import annotations

import logging

from sqlalchemy.ext.asyncio import AsyncSession

from src.models import InboundMessage
from src.whatsapp import observer
from src.whatsapp.observer import Observation

logger = logging.getLogger(__name__)


async def process_inbound(
    session: AsyncSession, model_router, row: InboundMessage
) -> tuple[Observation, str]:
    """Observe, classify, and decide what to do about one queued message.

    Raises on failure. The caller (the queue) turns that into a retry with
    backoff — never into a lost message.
    """
    observation = await observer.observe(
        session,
        model_router,
        handle=row.handle,
        name=row.name,
        body=row.body,
        direction=row.direction,
        simulated=row.simulated,
    )
    outcome = _describe(observation)
    return observation, outcome


def _describe(observation: Observation) -> str:
    """One-line summary stored on the queue row, for the activity dashboard."""
    parts = [f"mode={observation.mode.value}"]
    if observation.classification is not None:
        parts.append(f"intent={observation.classification.intent}")
        if observation.classification.sensitive:
            parts.append(f"sensitive={','.join(observation.classification.sensitive)}")
    parts.append(f"draft={'yes' if observation.draft else 'no'}")
    return "; ".join(parts)
