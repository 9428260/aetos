"""Optimizer – refines each candidate strategy via local search."""

import random
import uuid

from ..config import settings
from ..reward import compute_reward
from ..state import ESSAction, EnergyState, LoadAction, MarketBid, PVAction, Strategy
from .base import BaseAgent


class Optimizer(BaseAgent):
    """
    Runs a stochastic local search (random perturbation + hill-climbing)
    on each candidate strategy to improve its reward score.
    """

    def __init__(self, iterations: int | None = None) -> None:
        super().__init__("Optimizer")
        self.iterations = iterations or settings.optimizer_iterations

    def act(  # type: ignore[override]
        self,
        state: EnergyState,
        strategies: list[Strategy],
    ) -> list[Strategy]:
        self.perceive(state)
        return [self._local_search(state, s) for s in strategies]

    # ------------------------------------------------------------------
    def _local_search(self, state: EnergyState, strategy: Strategy) -> Strategy:
        best = strategy.model_copy(deep=True)
        best_reward = compute_reward(state, best)

        for _ in range(self.iterations):
            candidate = self._perturb(state, best)
            r = compute_reward(state, candidate)
            if r > best_reward:
                best, best_reward = candidate, r

        best.bid = best_reward
        return best

    def _perturb(self, state: EnergyState, s: Strategy) -> Strategy:
        """Apply a random multiplicative perturbation to each action dimension."""
        max_charge = settings.ess_max_charge_kw
        max_discharge = settings.ess_max_discharge_kw

        def jitter(v: float, lo: float = 0.0, hi: float = 1e9) -> float:
            return max(lo, min(hi, v * random.uniform(0.7, 1.3)))

        return Strategy(
            id=str(uuid.uuid4()),
            ess=ESSAction(
                charge_rate=jitter(s.ess.charge_rate, hi=max_charge),
                discharge_rate=jitter(s.ess.discharge_rate, hi=max_discharge),
            ),
            pv=PVAction(curtailment_ratio=jitter(s.pv.curtailment_ratio, hi=1.0)),
            load=LoadAction(
                shift_amount=jitter(s.load.shift_amount),
                shift_intervals=s.load.shift_intervals,
            ),
            market=MarketBid(
                quantity=jitter(s.market.quantity),
                price=jitter(s.market.price),
            ),
            metadata={**s.metadata, "parent": s.id},
        )
