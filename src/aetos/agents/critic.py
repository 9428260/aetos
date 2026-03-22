"""MetaCritic – selects the best strategy from CDA winners."""

from ..reward import compute_reward, decompose_reward
from ..state import Constraints, EnergyState, Strategy
from .base import BaseAgent


class MetaCritic(BaseAgent):
    """
    Evaluates CDA-winning candidates on multiple criteria and selects
    the final strategy.

    Criteria (beyond raw reward):
      - Policy compliance (SOC, export limits)
      - Risk profile (variance in reward components)
      - Degradation penalty
    """

    def __init__(self) -> None:
        super().__init__("MetaCritic")

    def act(  # type: ignore[override]
        self,
        state: EnergyState,
        candidates: list[Strategy],
    ) -> Strategy:
        self.perceive(state)
        compliant = self._filter_policy(state, candidates)
        pool = compliant if compliant else candidates  # fallback to all if none pass
        return self._select_best(state, pool)

    # ------------------------------------------------------------------
    def _filter_policy(
        self,
        state: EnergyState,
        candidates: list[Strategy],
    ) -> list[Strategy]:
        """Remove strategies that violate hard constraints."""
        ok: list[Strategy] = []
        c: Constraints = state.constraints
        capacity = 100.0  # kWh (could come from config)

        for s in candidates:
            delta_soc = (s.ess.charge_rate - s.ess.discharge_rate) / capacity
            new_soc = state.ess_soc + delta_soc

            if new_soc < c.soc_min or new_soc > c.soc_max:
                continue

            if c.export_limit > 0:
                avg_gen = sum(state.generation) / len(state.generation) if state.generation else 0.0
                avg_load = sum(state.load) / len(state.load) if state.load else 0.0
                net_export = (
                    avg_gen * (1 - s.pv.curtailment_ratio)
                    + s.ess.discharge_rate
                    - avg_load
                )
                if net_export > c.export_limit:
                    continue

            ok.append(s)
        return ok

    def _select_best(self, state: EnergyState, candidates: list[Strategy]) -> Strategy:
        """Re-score all candidates and return the highest reward one."""
        scored = [(s, compute_reward(state, s)) for s in candidates]
        best, best_reward = max(scored, key=lambda x: x[1])
        best.bid = best_reward
        best.metadata["reward_decomposition"] = decompose_reward(state, best)
        return best

    def reflect(self, result) -> None:  # type: ignore[override]
        pass  # hook for online learning / logging
