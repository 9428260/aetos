"""StrategyGenerator – produces a diverse set of candidate strategies."""

import uuid

from ..config import settings
from ..reward import compute_reward
from ..state import ESSAction, EnergyState, LoadAction, MarketBid, PVAction, Strategy
from .base import BaseAgent


class StrategyGenerator(BaseAgent):
    """
    Generates N candidate strategies covering different operating modes:
      1. Aggressive discharge   – prioritise ESS revenue
      2. Solar-first            – maximise PV self-consumption
      3. Load shifting          – defer flexible loads to off-peak
      4. ESS charge             – opportunistic charging at low price
      5. Market arbitrage       – export surplus at peak price
      6. Conservative           – minimal action / safety baseline
    """

    def __init__(self) -> None:
        super().__init__("StrategyGenerator")

    def act(self, state: EnergyState) -> list[Strategy]:  # type: ignore[override]
        self.perceive(state)
        ctx = self.reason()
        return self._generate_strategies(state, ctx)

    def _generate_strategies(self, state: EnergyState, ctx: dict) -> list[Strategy]:
        strategies: list[Strategy] = []

        avg_p = ctx["avg_price"]
        avg_l = ctx["avg_load"]
        avg_g = ctx["avg_gen"]
        soc_headroom = ctx["soc_headroom"]
        soc_margin = ctx["soc_margin"]

        max_charge = min(settings.ess_max_charge_kw, soc_headroom * settings.ess_capacity_kwh)
        max_discharge = min(settings.ess_max_discharge_kw, soc_margin * settings.ess_capacity_kwh)

        # 1. Aggressive discharge
        s1 = self._make(
            ess=ESSAction(discharge_rate=max_discharge),
            market=MarketBid(quantity=max_discharge * 0.8, price=avg_p * 1.15),
            meta={"mode": "aggressive_discharge"},
        )

        # 2. Solar-first (charge with excess PV, zero curtailment)
        excess_pv = max(0.0, avg_g - avg_l)
        s2 = self._make(
            ess=ESSAction(charge_rate=min(max_charge, excess_pv)),
            meta={"mode": "solar_first"},
        )

        # 3. Load shifting
        s3 = self._make(
            load=LoadAction(shift_amount=avg_l * 0.2, shift_intervals=2),
            meta={"mode": "load_shifting"},
        )

        # 4. ESS charge (store for later)
        s4 = self._make(
            ess=ESSAction(charge_rate=max_charge * 0.6),
            meta={"mode": "ess_charge"},
        )

        # 5. Market arbitrage (export surplus)
        net_gen = max(0.0, avg_g - avg_l)
        s5 = self._make(
            ess=ESSAction(discharge_rate=max_discharge * 0.5),
            pv=PVAction(curtailment_ratio=0.05),
            load=LoadAction(shift_amount=avg_l * 0.1, shift_intervals=1),
            market=MarketBid(quantity=net_gen + max_discharge * 0.5, price=avg_p * 1.10),
            meta={"mode": "market_arbitrage"},
        )

        # 6. Conservative baseline
        s6 = self._make(meta={"mode": "conservative"})

        for s in (s1, s2, s3, s4, s5, s6):
            s.bid = compute_reward(state, s)
            strategies.append(s)

        return strategies

    @staticmethod
    def _make(
        ess: ESSAction | None = None,
        pv: PVAction | None = None,
        load: LoadAction | None = None,
        market: MarketBid | None = None,
        meta: dict | None = None,
    ) -> Strategy:
        return Strategy(
            id=str(uuid.uuid4()),
            ess=ess or ESSAction(),
            pv=pv or PVAction(),
            load=load or LoadAction(),
            market=market or MarketBid(),
            metadata=meta or {},
        )
