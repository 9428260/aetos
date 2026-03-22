"""MetaCritic – selects the best strategy from CDA winners."""

from typing import Any

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
        *,
        similar_cases: list[dict[str, Any]] | None = None,
    ) -> Strategy:
        self.perceive(state)
        compliant = self._filter_policy(state, candidates)
        pool = compliant if compliant else candidates  # fallback to all if none pass
        return self._select_best(state, pool, similar_cases=similar_cases or [])

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

    def _select_best(
        self,
        state: EnergyState,
        candidates: list[Strategy],
        *,
        similar_cases: list[dict[str, Any]] | None = None,
    ) -> Strategy:
        """Re-score all candidates and return the highest reward one.

        When *similar_cases* are provided, a small memory bonus (+5 % weight)
        derived from the average historical reward for each mode is added to
        break ties in favour of modes that worked well in similar past states.
        """
        mode_avg = _build_mode_reward_map(similar_cases or [])
        memory_weight = 0.05

        def score(s: Strategy) -> float:
            base = compute_reward(state, s)
            mode = s.metadata.get("mode", "")
            bonus = mode_avg.get(mode, 0.0) * memory_weight
            return base + bonus

        scored = [(s, score(s)) for s in candidates]
        best, _ = max(scored, key=lambda x: x[1])
        best.bid = compute_reward(state, best)
        best.metadata["reward_decomposition"] = decompose_reward(state, best)
        return best

    def reflect(self, result) -> None:  # type: ignore[override]
        pass  # hook for online learning / logging


def _build_mode_reward_map(similar_cases: list[dict[str, Any]]) -> dict[str, float]:
    """Return average reward per mode across similar historical cases."""
    totals: dict[str, list[float]] = {}
    for case in similar_cases:
        mode = case.get("mode", "")
        reward = float(case.get("reward", 0.0))
        if mode:
            totals.setdefault(mode, []).append(reward)
    return {mode: sum(rewards) / len(rewards) for mode, rewards in totals.items()}
