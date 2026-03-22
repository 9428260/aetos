"""Execution layer – translates the selected strategy into physical setpoints."""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from ..state import EnergyState, Strategy

logger = logging.getLogger(__name__)


class Dispatcher:
    """Sends control commands to physical assets (ESS, inverter, smart loads).

    In production, ``dispatch`` would write setpoints to a SCADA / DER
    management system via Modbus, DNP3, or a REST API.  Here we log the
    action and return a structured record.
    """

    def __init__(self) -> None:
        self._log: list[dict] = []

    # ------------------------------------------------------------------
    def dispatch(self, state: EnergyState, strategy: Strategy) -> dict:
        """Apply the strategy and return the dispatched action record."""
        action = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "strategy_id": strategy.id,
            "mode": strategy.metadata.get("mode", "unknown"),
            # ESS setpoints
            "ess_charge_kw": strategy.ess.charge_rate,
            "ess_discharge_kw": strategy.ess.discharge_rate,
            # PV setpoint
            "pv_curtailment_ratio": strategy.pv.curtailment_ratio,
            # Load setpoint
            "load_shift_kw": strategy.load.shift_amount,
            "load_shift_intervals": strategy.load.shift_intervals,
            # Market order
            "market_quantity_kw": strategy.market.quantity,
            "market_price_per_kwh": strategy.market.price,
            # Reward
            "expected_reward": strategy.bid,
            # Reward decomposition (if available from MetaCritic)
            "reward_decomposition": strategy.metadata.get("reward_decomposition", {}),
        }

        logger.info(
            "DISPATCH  strategy=%s  ess=+%.1f/−%.1f kW  pv_curtail=%.0f%%  "
            "load_shift=%.1f kW  market=%.1f kW@%.4f$/kWh  reward=%.4f",
            strategy.id[:8],
            strategy.ess.charge_rate,
            strategy.ess.discharge_rate,
            strategy.pv.curtailment_ratio * 100,
            strategy.load.shift_amount,
            strategy.market.quantity,
            strategy.market.price,
            strategy.bid,
        )

        self._log.append(action)
        return action

    # ------------------------------------------------------------------
    def get_log(self) -> list[dict]:
        return list(self._log)
