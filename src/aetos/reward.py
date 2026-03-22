"""
Reward Function
===============
Reward =
  w1 * CostSaving
+ w2 * SolarROI
+ w3 * ESSProfit
- w4 * DegradationCost
- w5 * RiskPenalty
"""

from .config import settings
from .state import EnergyState, Strategy


def _avg(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def compute_reward(state: EnergyState, strategy: Strategy) -> float:  # noqa: C901
    avg_price = _avg(state.price) or 0.10  # fallback: 10 ¢/kWh
    avg_load = _avg(state.load)
    avg_gen = _avg(state.generation)

    ess_discharge = strategy.ess.discharge_rate
    ess_charge = strategy.ess.charge_rate
    pv_used = avg_gen * (1.0 - strategy.pv.curtailment_ratio)
    load_shifted = strategy.load.shift_amount

    # 1. CostSaving – reduction in grid-import cost
    #    (discharge + solar + load deferred → less grid draw)
    grid_reduction = ess_discharge + pv_used - max(0.0, avg_load - load_shifted)
    cost_saving = grid_reduction * avg_price

    # 2. SolarROI – value of solar energy consumed or exported
    solar_roi = pv_used * avg_price

    # 3. ESSProfit – charge cheap, discharge expensive (simplified)
    #    Assume charge happens at 80 % of current avg_price (off-peak)
    ess_profit = ess_discharge * avg_price - ess_charge * avg_price * 0.8

    # 4. DegradationCost – per kWh cycled through the ESS
    degradation = (ess_charge + ess_discharge) * settings.ess_degradation_cost_per_kwh

    # 5. RiskPenalty – SOC constraint violations
    #    Simplified: net SOC change per interval (1 h assumed)
    capacity = settings.ess_capacity_kwh
    delta_soc = (ess_charge - ess_discharge) / capacity
    new_soc = state.ess_soc + delta_soc
    soc_over = max(0.0, new_soc - state.constraints.soc_max)
    soc_under = max(0.0, state.constraints.soc_min - new_soc)
    risk_penalty = (soc_over + soc_under) * 10.0

    # Export limit violation penalty
    net_export = pv_used + ess_discharge - avg_load
    if state.constraints.export_limit > 0 and net_export > state.constraints.export_limit:
        risk_penalty += (net_export - state.constraints.export_limit) * 5.0

    reward = (
        settings.w1_cost_saving * cost_saving
        + settings.w2_solar_roi * solar_roi
        + settings.w3_ess_profit * ess_profit
        - settings.w4_degradation * degradation
        - settings.w5_risk * risk_penalty
    )
    return round(reward, 6)


def decompose_reward(state: EnergyState, strategy: Strategy) -> dict[str, float]:
    """Return each reward component for observability / KPI tracking."""
    avg_price = _avg(state.price) or 0.10
    avg_gen = _avg(state.generation)
    avg_load = _avg(state.load)

    pv_used = avg_gen * (1.0 - strategy.pv.curtailment_ratio)
    grid_reduction = strategy.ess.discharge_rate + pv_used - max(0.0, avg_load - strategy.load.shift_amount)
    cost_saving = grid_reduction * avg_price
    solar_roi = pv_used * avg_price
    ess_profit = strategy.ess.discharge_rate * avg_price - strategy.ess.charge_rate * avg_price * 0.8
    degradation = (strategy.ess.charge_rate + strategy.ess.discharge_rate) * settings.ess_degradation_cost_per_kwh

    delta_soc = (strategy.ess.charge_rate - strategy.ess.discharge_rate) / settings.ess_capacity_kwh
    new_soc = state.ess_soc + delta_soc
    soc_over = max(0.0, new_soc - state.constraints.soc_max)
    soc_under = max(0.0, state.constraints.soc_min - new_soc)
    risk_penalty = (soc_over + soc_under) * 10.0

    return {
        "cost_saving": round(cost_saving, 4),
        "solar_roi": round(solar_roi, 4),
        "ess_profit": round(ess_profit, 4),
        "degradation_cost": round(degradation, 4),
        "risk_penalty": round(risk_penalty, 4),
        "total": round(compute_reward(state, strategy), 6),
    }
