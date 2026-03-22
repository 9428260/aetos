"""
MCP Tool Layer
==============

Exposes five tools via the Model Context Protocol (FastMCP):

  forecast      – price / load / generation forecast
  optimize      – run full optimization workflow on a state
  policy_check  – validate strategy against grid constraints
  dispatch      – send setpoints (dry-run or live)
  kpi           – retrieve latest KPI snapshot
"""

from __future__ import annotations

import json
import logging
import random
from datetime import datetime, timezone

from mcp.server.fastmcp import FastMCP

from ..agents.critic import MetaCritic
from ..agents.optimizer import Optimizer
from ..agents.strategy import StrategyGenerator
from ..execution.dispatch import Dispatcher
from ..negotiation.cda import CDAMarket
from ..reward import compute_reward, decompose_reward
from ..state import Constraints, EnergyState, Strategy

logger = logging.getLogger(__name__)

mcp = FastMCP("aetos-energy")

# Shared agent instances
_strategy_gen = StrategyGenerator()
_optimizer = Optimizer()
_market = CDAMarket(min_candidates=2)
_critic = MetaCritic()
_dispatcher = Dispatcher()


# ---------------------------------------------------------------------------
# Tool: forecast
# ---------------------------------------------------------------------------


@mcp.tool()
def forecast(horizon: int = 24) -> dict:
    """
    Forecast electricity price, load, and solar generation.

    Args:
        horizon: Number of 1-hour intervals to forecast (default 24).

    Returns:
        dict with keys 'price' ($/kWh), 'load' (kW), 'generation' (kW).
    """
    hour_now = datetime.now().hour
    price, load, generation = [], [], []

    for i in range(horizon):
        h = (hour_now + i) % 24
        price.append(round(0.04 + 0.06 * (9 <= h <= 18) + random.gauss(0, 0.005), 4))
        load.append(round(max(0, 20 + 15 * (8 <= h <= 21) + random.gauss(0, 2)), 2))
        generation.append(round(max(0, 30 * (1 - abs(h - 13) / 8) + random.gauss(0, 1)), 2))

    return {"price": price, "load": load, "generation": generation}


# ---------------------------------------------------------------------------
# Tool: optimize
# ---------------------------------------------------------------------------


@mcp.tool()
def optimize(state: dict) -> dict:
    """
    Run the full optimization workflow (generate → optimize → auction → critique).

    Args:
        state: EnergyState as a JSON-serialisable dict.

    Returns:
        Selected strategy as a JSON-serialisable dict with 'reward' field.
    """
    energy = EnergyState(**state)
    strategies = _strategy_gen.act(energy)
    optimized = _optimizer.act(energy, strategies)
    winners = _market.auction(optimized)
    selected = _critic.act(energy, winners)
    result = selected.model_dump()
    result["reward"] = compute_reward(energy, selected)
    result["reward_decomposition"] = decompose_reward(energy, selected)
    return result


# ---------------------------------------------------------------------------
# Tool: policy_check
# ---------------------------------------------------------------------------


@mcp.tool()
def policy_check(strategy: dict, state: dict) -> dict:
    """
    Check whether a strategy complies with grid and system constraints.

    Args:
        strategy: Strategy dict.
        state:    EnergyState dict.

    Returns:
        dict with 'compliant' (bool) and 'violations' (list[str]).
    """
    s = Strategy(**strategy)
    energy = EnergyState(**state)
    c: Constraints = energy.constraints

    violations: list[str] = []

    if s.ess.charge_rate < 0:
        violations.append("ESS charge_rate must be non-negative")
    if s.ess.discharge_rate < 0:
        violations.append("ESS discharge_rate must be non-negative")
    if not (0.0 <= s.pv.curtailment_ratio <= 1.0):
        violations.append("PV curtailment_ratio must be in [0, 1]")

    capacity = 100.0  # kWh
    delta_soc = (s.ess.charge_rate - s.ess.discharge_rate) / capacity
    new_soc = energy.ess_soc + delta_soc

    if new_soc < c.soc_min:
        violations.append(f"New SOC {new_soc:.3f} < soc_min {c.soc_min}")
    if new_soc > c.soc_max:
        violations.append(f"New SOC {new_soc:.3f} > soc_max {c.soc_max}")

    if c.export_limit > 0:
        avg_gen = sum(energy.generation) / len(energy.generation) if energy.generation else 0.0
        avg_load = sum(energy.load) / len(energy.load) if energy.load else 0.0
        net_export = avg_gen * (1 - s.pv.curtailment_ratio) + s.ess.discharge_rate - avg_load
        if net_export > c.export_limit:
            violations.append(
                f"Net export {net_export:.1f} kW exceeds limit {c.export_limit} kW"
            )

    return {"compliant": len(violations) == 0, "violations": violations}


# ---------------------------------------------------------------------------
# Tool: dispatch
# ---------------------------------------------------------------------------


@mcp.tool()
def dispatch(strategy: dict, state: dict | None = None, dry_run: bool = True) -> dict:
    """
    Dispatch a strategy to physical assets.

    Args:
        strategy: Strategy dict.
        state:    Optional EnergyState dict (used for reward calculation).
        dry_run:  If True (default) only log; do not send to hardware.

    Returns:
        Dispatched action record.
    """
    s = Strategy(**strategy)
    energy = EnergyState(**(state or {}))
    action = _dispatcher.dispatch(energy, s)
    action["dry_run"] = dry_run
    return action


# ---------------------------------------------------------------------------
# Tool: kpi
# ---------------------------------------------------------------------------


@mcp.tool()
def kpi() -> dict:
    """
    Return the latest KPI snapshot from the dispatcher log.

    Returns:
        dict with cost_saving, ess_profit, solar_roi, total_reward.
    """
    log = _dispatcher.get_log()
    if not log:
        return {"cost_saving": 0.0, "ess_profit": 0.0, "solar_roi": 0.0, "total_reward": 0.0, "n_dispatches": 0}

    total_reward = sum(entry.get("expected_reward", 0.0) for entry in log)
    decomps = [entry.get("reward_decomposition", {}) for entry in log]
    cost_saving = sum(d.get("cost_saving", 0.0) for d in decomps)
    ess_profit = sum(d.get("ess_profit", 0.0) for d in decomps)
    solar_roi = sum(d.get("solar_roi", 0.0) for d in decomps)

    return {
        "cost_saving": round(cost_saving, 4),
        "ess_profit": round(ess_profit, 4),
        "solar_roi": round(solar_roi, 4),
        "total_reward": round(total_reward, 4),
        "n_dispatches": len(log),
        "last_dispatch": log[-1]["timestamp"],
    }


# ---------------------------------------------------------------------------
# Entry point (stdio transport)
# ---------------------------------------------------------------------------


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    mcp.run()


if __name__ == "__main__":
    main()
