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

import logging

from mcp.server.fastmcp import FastMCP

from ..observability import audit_log, metrics, timed
from ..runtime import runtime
from ..state import EnergyState, Strategy

logger = logging.getLogger(__name__)

mcp = FastMCP("aetos-energy")


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
    metrics.incr("mcp.forecast.calls")
    with timed("mcp.forecast", audit_event="mcp.forecast", horizon=horizon):
        return runtime.forecast(horizon)


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
    energy = EnergyState.model_validate(state)
    metrics.incr("mcp.optimize.calls")
    with timed("mcp.optimize", audit_event="mcp.optimize"):
        return runtime.optimize_via_a2a(energy)


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
    s = Strategy.model_validate(strategy)
    energy = EnergyState.model_validate(state)
    metrics.incr("mcp.policy_check.calls")
    with timed("mcp.policy_check", audit_event="mcp.policy_check"):
        return runtime.policy_check(s, energy)


# ---------------------------------------------------------------------------
# Tool: dispatch
# ---------------------------------------------------------------------------


@mcp.tool()
def dispatch(
    strategy: dict,
    state: dict | None = None,
    dry_run: bool = True,
    idempotency_key: str | None = None,
) -> dict:
    """
    Dispatch a strategy to physical assets.

    Args:
        strategy: Strategy dict.
        state:    Optional EnergyState dict (used for reward calculation).
        dry_run:  If True (default) only log; do not send to hardware.

    Returns:
        Dispatched action record.
    """
    s = Strategy.model_validate(strategy)
    energy = EnergyState.model_validate(state) if state is not None else None
    metrics.incr("mcp.dispatch.calls")
    with timed("mcp.dispatch", audit_event="mcp.dispatch", dry_run=dry_run):
        return runtime.dispatch_via_a2a(
            s,
            energy,
            dry_run=dry_run,
            idempotency_key=idempotency_key,
        )


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
    metrics.incr("mcp.kpi.calls")
    with timed("mcp.kpi", audit_event="mcp.kpi"):
        return runtime.kpi()


# ---------------------------------------------------------------------------
# Entry point (stdio transport)
# ---------------------------------------------------------------------------


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    mcp.run()


if __name__ == "__main__":
    main()
