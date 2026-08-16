"""Usage and cost tracking.

Two very different kinds of number live here, and the distinction matters:

  * **Token counts are facts.** Providers report them; we store them verbatim.
  * **Costs are estimates.** They come from a price table that can drift when
    vendors change pricing. Everything that displays a cost calls it an
    estimate, and the table is overridable from .env.

Local calls are recorded at 0.0 — the one cost that is certainly exact.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.llm.base import Usage
from src.models import ModelUsage

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Price:
    """USD per 1 million tokens."""

    input_per_m: float
    output_per_m: float


# Published list prices as of 2026-08. These WILL drift — treat as estimates
# and override with LLM_PRICES in .env if they matter to you.
# Anything not listed is treated as free (locals) or unknown (0.0) rather
# than guessed at, because a fabricated cost is worse than an absent one.
DEFAULT_PRICES: dict[str, Price] = {
    "gemini-2.5-flash": Price(0.30, 2.50),
    "gpt-5.1": Price(1.25, 10.00),
    "claude-sonnet-5": Price(3.00, 15.00),
}


def price_for(model: str) -> Price | None:
    """Exact match first, then prefix — model ids often carry date suffixes."""
    if model in DEFAULT_PRICES:
        return DEFAULT_PRICES[model]
    for known, price in DEFAULT_PRICES.items():
        if model.startswith(known):
            return price
    return None


def estimate_cost(model: str, usage: Usage, *, is_local: bool) -> float:
    """Estimated USD for one call. Local is exactly zero."""
    if is_local:
        return 0.0
    price = price_for(model)
    if price is None:
        # Unknown model: record the tokens, admit we cannot price it.
        return 0.0
    return round(
        usage.input_tokens / 1_000_000 * price.input_per_m
        + usage.output_tokens / 1_000_000 * price.output_per_m,
        6,
    )


async def record(
    session: AsyncSession,
    *,
    provider: str,
    model: str,
    tier: str,
    task_class: str,
    usage: Usage | None,
) -> None:
    """Store one call's usage. Never raises — accounting must not break a reply."""
    if usage is None:
        return
    try:
        session.add(
            ModelUsage(
                provider=provider,
                model=model,
                tier=tier,
                task_class=task_class,
                input_tokens=usage.input_tokens,
                output_tokens=usage.output_tokens,
                estimated_cost_usd=estimate_cost(
                    model, usage, is_local=tier.startswith("local")
                ),
            )
        )
        await session.commit()
    except Exception as exc:  # noqa: BLE001 — losing a metric must not lose the answer
        logger.warning("Failed to record model usage: %s", exc)


async def summary(session: AsyncSession) -> dict:
    """Usage rolled up by period and by model, for the Costs page."""
    now = datetime.now(timezone.utc)
    periods = {
        "today": now - timedelta(days=1),
        "week": now - timedelta(days=7),
        "month": now - timedelta(days=30),
        "all_time": datetime(1970, 1, 1, tzinfo=timezone.utc),
    }

    totals: dict[str, dict] = {}
    for label, since in periods.items():
        row = (
            await session.execute(
                select(
                    func.count(ModelUsage.id),
                    func.coalesce(func.sum(ModelUsage.input_tokens), 0),
                    func.coalesce(func.sum(ModelUsage.output_tokens), 0),
                    func.coalesce(func.sum(ModelUsage.estimated_cost_usd), 0.0),
                ).where(ModelUsage.created_at >= since)
            )
        ).one()
        totals[label] = {
            "calls": row[0],
            "input_tokens": int(row[1]),
            "output_tokens": int(row[2]),
            "estimated_cost_usd": round(float(row[3]), 4),
        }

    by_model_rows = (
        await session.execute(
            select(
                ModelUsage.model,
                ModelUsage.tier,
                func.count(ModelUsage.id),
                func.coalesce(func.sum(ModelUsage.estimated_cost_usd), 0.0),
            )
            .group_by(ModelUsage.model, ModelUsage.tier)
            .order_by(func.count(ModelUsage.id).desc())
        )
    ).all()

    by_model = [
        {
            "model": m,
            "tier": t,
            "calls": c,
            "estimated_cost_usd": round(float(cost), 4),
            "local": t.startswith("local"),
        }
        for m, t, c, cost in by_model_rows
    ]

    local_calls = sum(m["calls"] for m in by_model if m["local"])
    total_calls = sum(m["calls"] for m in by_model) or 1

    return {
        "totals": totals,
        "by_model": by_model,
        "local_share_pct": round(local_calls / total_calls * 100),
        "note": (
            "Token counts are reported by the provider and are exact. Costs "
            "are estimates from a published price table and may drift."
        ),
    }
