"""
Execution Loop
==============

while True:
    state  = get_state()
    action = workflow(state)
    apply(action)     # via Dispatcher
    reward = evaluate(action, state)
    store(state, action, reward)
"""

from __future__ import annotations

import asyncio
import logging
import random
import uuid
from datetime import datetime, timezone

from .config import settings
from .db.models import Episode, KPI
from .db.session import AsyncSessionLocal, init_db
from .state import Constraints, EnergyState
from .workflow import run_workflow

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# State acquisition (replace with real SCADA / sensor integration)
# ---------------------------------------------------------------------------


async def get_state() -> EnergyState:
    """Fetch the current energy state snapshot.

    In production this should query your SCADA, BMS, or metering API.
    """
    hour = datetime.now().hour
    prices = [
        round(max(0.01, 0.04 + 0.06 * (9 <= (hour + i) % 24 <= 18) + random.gauss(0, 0.005)), 4)
        for i in range(24)
    ]
    loads = [
        round(max(0, 20 + 15 * (8 <= (hour + i) % 24 <= 21) + random.gauss(0, 2)), 2)
        for i in range(24)
    ]
    generation = [
        round(max(0, 30 * (1 - abs((hour + i) % 24 - 13) / 8) + random.gauss(0, 1)), 2)
        for i in range(24)
    ]
    return EnergyState(
        price=prices,
        load=loads,
        generation=generation,
        ess_soc=round(random.uniform(0.3, 0.7), 2),
        constraints=Constraints(export_limit=50.0, soc_min=0.1, soc_max=0.9),
        timestamp=datetime.now(timezone.utc).isoformat(),
    )


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------


async def store(state: EnergyState, result: dict) -> None:
    selected = result.get("selected")
    reward = result.get("reward", 0.0)
    decomp = selected.metadata.get("reward_decomposition", {}) if selected else {}

    async with AsyncSessionLocal() as session:
        ep = Episode(
            id=str(uuid.uuid4()),
            timestamp=datetime.now(timezone.utc),
            state=state.model_dump(),
            action=selected.model_dump() if selected else {},
            reward=reward,
        )
        kpi = KPI(
            id=str(uuid.uuid4()),
            timestamp=datetime.now(timezone.utc),
            cost_saving=decomp.get("cost_saving", reward * 0.3),
            ess_profit=decomp.get("ess_profit", reward * 0.3),
            roi=decomp.get("solar_roi", reward * 0.2),
        )
        session.add(ep)
        session.add(kpi)
        await session.commit()


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------


async def main_loop() -> None:
    await init_db()
    logger.info("AETOS execution loop started (interval=%ds)", settings.interval_seconds)

    while True:
        try:
            state = await get_state()
            result = await run_workflow(state)
            await store(state, result)

            logger.info(
                "cycle complete  reward=%.4f  messages=%s",
                result.get("reward", 0.0),
                result.get("messages", []),
            )
        except Exception:
            logger.exception("Loop error – continuing")

        await asyncio.sleep(settings.interval_seconds)


def main() -> None:
    logging.basicConfig(
        level=settings.log_level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    asyncio.run(main_loop())


if __name__ == "__main__":
    main()
