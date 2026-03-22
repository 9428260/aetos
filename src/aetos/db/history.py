"""Persist optimisation workflow runs to the database (audit / replay)."""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Literal

from ..state import EnergyState
from .models import Episode, KPI

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

SourceKind = Literal["api", "loop"]


def _reward_decomposition(result: dict) -> dict:
    selected = result.get("selected")
    if not selected:
        return {}
    return selected.metadata.get("reward_decomposition", {}) or {}


def _kpi_values(result: dict, decomp: dict) -> tuple[float, float, float]:
    reward = float(result.get("reward", 0.0))
    return (
        float(decomp.get("cost_saving", reward * 0.3)),
        float(decomp.get("ess_profit", reward * 0.3)),
        float(decomp.get("solar_roi", reward * 0.2)),
    )


async def persist_workflow_run(
    state: EnergyState,
    result: dict,
    *,
    source: SourceKind = "api",
    session: "AsyncSession | None" = None,
) -> str | None:
    """Store one decision cycle: full trace in ``Episode``, KPI row linked by ``episode_id``.

    Returns the new episode id, or ``None`` if the database write failed.
    """
    selected = result.get("selected")
    reward = float(result.get("reward", 0.0))
    decomp = _reward_decomposition(result)
    step_events = result.get("step_events") or []
    messages = result.get("messages") or []

    cost_saving, ess_profit, roi = _kpi_values(result, decomp)
    episode_id = str(uuid.uuid4())
    ts = datetime.now(timezone.utc)

    ep = Episode(
        id=episode_id,
        timestamp=ts,
        state=state.model_dump(),
        action=selected.model_dump() if selected else {},
        reward=reward,
        step_events=step_events,
        messages=messages,
        reward_decomposition=decomp,
        source=source,
    )
    kpi = KPI(
        id=str(uuid.uuid4()),
        timestamp=ts,
        episode_id=episode_id,
        cost_saving=cost_saving,
        ess_profit=ess_profit,
        roi=roi,
    )

    from sqlalchemy.ext.asyncio import AsyncSession
    from .session import AsyncSessionLocal

    async def _commit(s: AsyncSession) -> None:
        s.add(ep)
        s.add(kpi)
        await s.commit()

    if session is not None:
        try:
            await _commit(session)
            return episode_id
        except Exception as e:
            logger.debug("DB persist failed: %s", e)
            return None

    try:
        async with AsyncSessionLocal() as s:
            await _commit(s)
        return episode_id
    except Exception as e:
        logger.debug("DB persist skipped: %s", e)
        return None
