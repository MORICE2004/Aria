"""Model router — picks the right model for the job.

ARIA should not send "classify this message" to a premium cloud model, nor
"analyse this contract" to a 3B local model. Callers declare WHAT KIND of
work they need; the router decides WHERE it runs.

Design rules:
  * Callers never name a vendor. They pass a TaskClass.
  * Local first where it is good enough — free, private, offline-capable.
  * Cloud when the task genuinely needs stronger reasoning.
  * Always fall back rather than fail: if the preferred tier is unavailable
    (Ollama not running, no cloud key), try the next one and say so in the log.
"""

import logging
from dataclasses import dataclass
from enum import Enum

from src.core.config import get_settings
from src.llm.base import LLMProvider

logger = logging.getLogger(__name__)


class TaskClass(str, Enum):
    """What kind of thinking a call needs.

    ROUTINE  — classification, extraction, summarisation, tagging. Cheap,
               high volume, low risk. Local models handle these well.
    CONVERSE — chat and drafting. Quality matters, but not deep reasoning.
    REASON   — analysis, scoring, code review, planning. Worth cloud money.
    """

    ROUTINE = "routine"
    CONVERSE = "converse"
    REASON = "reason"


class Tier(str, Enum):
    """Where a call can run. Ordered cheapest/most-private first."""

    LOCAL_FAST = "local_fast"
    LOCAL_REASONING = "local_reasoning"
    CLOUD = "cloud"


# Preference order per task class. First available tier wins.
_ROUTING: dict[TaskClass, tuple[Tier, ...]] = {
    TaskClass.ROUTINE: (Tier.LOCAL_FAST, Tier.CLOUD),
    TaskClass.CONVERSE: (Tier.LOCAL_FAST, Tier.CLOUD),
    TaskClass.REASON: (Tier.CLOUD, Tier.LOCAL_REASONING, Tier.LOCAL_FAST),
}


@dataclass(frozen=True)
class Routed:
    """A resolved provider plus how it was chosen — for observability.

    `description` is safe to show the user ("ran locally on llama3.2:3b").
    It is an action explanation, not chain-of-thought.
    """

    provider: LLMProvider
    tier: Tier
    model: str

    @property
    def description(self) -> str:
        where = "locally" if self.tier.value.startswith("local") else "in the cloud"
        return f"ran {where} on {self.model}"


class ModelRouter:
    """Resolves a TaskClass to a concrete provider, with fallback."""

    def __init__(self) -> None:
        self._settings = get_settings()

    def resolve(self, task: TaskClass) -> Routed:
        """Return the best available provider for this kind of work."""
        attempted: list[str] = []
        for tier in self._preference_order(task):
            routed = self._build(tier)
            if routed is not None:
                if attempted:
                    logger.info(
                        "Router: %s fell back past %s -> %s",
                        task.value, ", ".join(attempted), routed.model,
                    )
                return routed
            attempted.append(tier.value)

        raise RuntimeError(
            "No LLM provider is available. Either start Ollama and pull a model "
            "(`ollama pull llama3.2:3b`), or set LLM_PROVIDER plus the matching "
            "API key in .env."
        )

    def _preference_order(self, task: TaskClass) -> tuple[Tier, ...]:
        order = _ROUTING[task]
        if task is TaskClass.CONVERSE and not self._settings.converse_local:
            # User prefers cloud quality for conversation over local privacy.
            order = (Tier.CLOUD, Tier.LOCAL_FAST)
        if self._settings.prefer_local:
            # Push local tiers ahead of cloud without losing relative order.
            local = tuple(t for t in order if t is not Tier.CLOUD)
            cloud = tuple(t for t in order if t is Tier.CLOUD)
            return local + cloud
        return order

    def _build(self, tier: Tier) -> Routed | None:
        """Construct a provider for this tier, or None if not configured."""
        s = self._settings

        if tier in (Tier.LOCAL_FAST, Tier.LOCAL_REASONING):
            model = (
                s.ollama_fast_model
                if tier is Tier.LOCAL_FAST
                else s.ollama_reasoning_model
            )
            if not model:
                return None
            from src.llm.ollama import OllamaProvider

            return Routed(
                provider=OllamaProvider(base_url=s.ollama_base_url, model=model),
                tier=tier,
                model=model,
            )

        # Cloud: whichever provider is configured, via the existing factory.
        from src.llm import build_cloud_provider

        built = build_cloud_provider()
        if built is None:
            return None
        provider, model = built
        return Routed(provider=provider, tier=Tier.CLOUD, model=model)
