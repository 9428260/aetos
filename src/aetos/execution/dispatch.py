"""Execution layer – translates the selected strategy into physical setpoints."""

from __future__ import annotations

import logging
import threading
from datetime import datetime, timezone

from ..config import settings
from ..observability import audit_log, metrics
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
        self._lock = threading.RLock()
        self._seen_idempotency_keys: set[str] = set()

    # ------------------------------------------------------------------
    def dispatch(
        self,
        state: EnergyState,
        strategy: Strategy,
        *,
        dry_run: bool = True,
        idempotency_key: str | None = None,
    ) -> dict:
        """Apply the strategy and return the dispatched action record."""
        if not dry_run:
            if not settings.dispatch_live_enabled:
                raise RuntimeError("live dispatch is disabled by configuration")
            if settings.dispatch_require_idempotency_key and not idempotency_key:
                raise RuntimeError("live dispatch requires an idempotency key")

        with self._lock:
            if idempotency_key and idempotency_key in self._seen_idempotency_keys:
                raise RuntimeError(f"duplicate dispatch idempotency key '{idempotency_key}'")
            if idempotency_key:
                self._seen_idempotency_keys.add(idempotency_key)

        max_power = settings.dispatch_max_power_kw
        if abs(strategy.ess.charge_rate) > max_power or abs(strategy.ess.discharge_rate) > max_power:
            raise RuntimeError("ESS setpoint exceeds dispatch_max_power_kw")
        if abs(strategy.market.quantity) > max_power:
            raise RuntimeError("market quantity exceeds dispatch_max_power_kw")
        if strategy.market.price > settings.dispatch_max_market_price:
            raise RuntimeError("market price exceeds dispatch_max_market_price")

        action = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "strategy_id": strategy.id,
            "mode": strategy.metadata.get("mode", "unknown"),
            "dry_run": dry_run,
            "idempotency_key": idempotency_key,
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

        with self._lock:
            self._log.append(action)
        metrics.incr("dispatch.total")
        if dry_run:
            metrics.incr("dispatch.dry_run")
        else:
            metrics.incr("dispatch.live")
        audit_log(
            "dispatch.executed",
            strategy_id=strategy.id,
            dry_run=dry_run,
            mode=action["mode"],
            market_quantity_kw=action["market_quantity_kw"],
        )
        return action

    # ------------------------------------------------------------------
    def get_log(self) -> list[dict]:
        with self._lock:
            return list(self._log)
