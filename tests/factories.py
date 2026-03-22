"""Test data factory functions.

Usage:
    from tests.factories import make_state, ScenarioFactory

    state = make_state("peak_hours")
    state = ScenarioFactory.solar_peak()
    state = ScenarioFactory.random(seed=42)
"""

from __future__ import annotations

import math
import random
from typing import Literal

from aetos.state import Constraints, EnergyState, ESSAction, LoadAction, MarketBid, PVAction, Strategy

# ─────────────────────────────────────────────────────────────────────────────
# Scenario names
# ─────────────────────────────────────────────────────────────────────────────

ScenarioName = Literal[
    "peak_hours",
    "off_peak",
    "solar_peak",
    "low_soc",
    "high_soc",
    "export_constrained",
    "price_spike",
    "cloudy_day",
    "winter_morning",
    "summer_noon",
]

SCENARIOS: dict[str, dict] = {
    # ── 피크 시간대: 높은 가격, 높은 부하, 보통 발전량
    "peak_hours": dict(
        price=[
            0.05, 0.05, 0.05, 0.05, 0.06, 0.07,  # 00–05
            0.09, 0.12, 0.18, 0.20, 0.19, 0.17,  # 06–11
            0.16, 0.18, 0.20, 0.22, 0.21, 0.20,  # 12–17
            0.18, 0.15, 0.12, 0.09, 0.07, 0.05,  # 18–23
        ],
        load=[
            18, 17, 16, 16, 17, 20,
            28, 38, 48, 52, 50, 48,
            46, 50, 55, 60, 58, 55,
            50, 42, 35, 28, 22, 19,
        ],
        generation=[
            0, 0, 0, 0, 0, 0,
            2, 8, 18, 26, 30, 32,
            33, 30, 25, 18, 10, 3,
            0, 0, 0, 0, 0, 0,
        ],
        ess_soc=0.50,
        constraints=Constraints(export_limit=50.0, soc_min=0.1, soc_max=0.9),
    ),

    # ── 심야 오프피크: 낮은 가격, 낮은 부하, 발전 없음
    "off_peak": dict(
        price=[0.035] * 8 + [0.05] * 8 + [0.04] * 8,
        load=[14, 13, 12, 12, 13, 14, 16, 18] + [22] * 8 + [16, 15, 14, 14, 14, 14, 14, 14],
        generation=[0] * 24,
        ess_soc=0.30,
        constraints=Constraints(export_limit=0.0, soc_min=0.1, soc_max=0.9),
    ),

    # ── 태양광 피크: 맑은 날 정오, 과잉 발전 처리 필요
    "solar_peak": dict(
        price=[
            0.04, 0.04, 0.04, 0.04, 0.05, 0.06,
            0.08, 0.10, 0.11, 0.10, 0.09, 0.08,
            0.07, 0.08, 0.10, 0.12, 0.13, 0.12,
            0.10, 0.08, 0.06, 0.05, 0.04, 0.04,
        ],
        load=[
            16, 15, 14, 14, 15, 17,
            22, 30, 36, 38, 37, 36,
            35, 36, 38, 40, 42, 40,
            36, 30, 25, 20, 18, 16,
        ],
        generation=[
            0, 0, 0, 0, 0, 1,
            5, 15, 28, 40, 48, 52,
            54, 50, 44, 34, 20, 8,
            2, 0, 0, 0, 0, 0,
        ],
        ess_soc=0.40,
        constraints=Constraints(export_limit=50.0, soc_min=0.1, soc_max=0.9),
    ),

    # ── 저 SOC: ESS 거의 방전, 충전 전략 선호
    "low_soc": dict(
        price=[0.06, 0.07, 0.08, 0.09, 0.10, 0.11] * 4,
        load=[30, 32, 35, 40, 45, 42] * 4,
        generation=[0, 0, 5, 15, 25, 10] * 4,
        ess_soc=0.12,  # 거의 방전
        constraints=Constraints(export_limit=30.0, soc_min=0.1, soc_max=0.9),
    ),

    # ── 고 SOC: ESS 거의 충전, 방전 전략 선호
    "high_soc": dict(
        price=[0.10, 0.12, 0.15, 0.18, 0.20, 0.16] * 4,
        load=[35, 38, 42, 48, 50, 45] * 4,
        generation=[0, 2, 10, 20, 28, 12] * 4,
        ess_soc=0.88,  # 거의 충전
        constraints=Constraints(export_limit=50.0, soc_min=0.1, soc_max=0.9),
    ),

    # ── 수출 제약: 계통 역조류 엄격 제한
    "export_constrained": dict(
        price=[0.05, 0.06, 0.08, 0.10, 0.09, 0.07] * 4,
        load=[20, 22, 25, 28, 26, 22] * 4,
        generation=[0, 0, 8, 30, 45, 18] * 4,
        ess_soc=0.60,
        constraints=Constraints(export_limit=5.0, soc_min=0.1, soc_max=0.9),  # 수출 5kW 제한
    ),

    # ── 가격 급등: 수요 반응 이벤트 (특정 시간 가격 폭등)
    "price_spike": dict(
        price=[
            0.05, 0.05, 0.05, 0.05, 0.06, 0.07,
            0.09, 0.12, 0.40, 0.55, 0.60, 0.45,  # 08–11 가격 급등
            0.25, 0.20, 0.15, 0.12, 0.10, 0.09,
            0.08, 0.07, 0.06, 0.05, 0.05, 0.05,
        ],
        load=[18, 17, 16, 16, 18, 22, 30, 40, 52, 55, 53, 50,
              48, 50, 52, 50, 48, 45, 40, 35, 28, 22, 20, 18],
        generation=[0, 0, 0, 0, 0, 1, 5, 14, 24, 32, 38, 40,
                    39, 35, 28, 20, 12, 4, 1, 0, 0, 0, 0, 0],
        ess_soc=0.70,
        constraints=Constraints(export_limit=50.0, soc_min=0.1, soc_max=0.9),
    ),

    # ── 흐린 날: 태양광 발전 불안정, 낮은 출력
    "cloudy_day": dict(
        price=[0.04, 0.04, 0.04, 0.05, 0.06, 0.07,
               0.09, 0.11, 0.12, 0.12, 0.11, 0.10,
               0.10, 0.11, 0.12, 0.13, 0.12, 0.11,
               0.09, 0.07, 0.06, 0.05, 0.04, 0.04],
        load=[15, 14, 13, 13, 14, 16, 22, 30, 36, 38, 36, 35,
              34, 35, 37, 40, 42, 40, 36, 30, 24, 20, 17, 15],
        generation=[0, 0, 0, 0, 0, 0, 1, 4, 8, 10, 8, 12,
                    14, 10, 8, 6, 3, 1, 0, 0, 0, 0, 0, 0],  # 낮은 발전
        ess_soc=0.55,
        constraints=Constraints(export_limit=20.0, soc_min=0.1, soc_max=0.9),
    ),

    # ── 겨울 아침: 낮은 태양광, 높은 난방 부하
    "winter_morning": dict(
        price=[0.06, 0.06, 0.07, 0.08, 0.10, 0.14,
               0.18, 0.22, 0.20, 0.17, 0.15, 0.13,
               0.12, 0.13, 0.15, 0.18, 0.20, 0.19,
               0.16, 0.13, 0.10, 0.08, 0.07, 0.06],
        load=[35, 34, 33, 34, 38, 48, 58, 62, 58, 52, 48, 45,
              43, 45, 48, 55, 60, 58, 52, 46, 40, 38, 36, 35],
        generation=[0, 0, 0, 0, 0, 0, 0, 3, 8, 12, 14, 15,
                    14, 12, 9, 5, 2, 0, 0, 0, 0, 0, 0, 0],
        ess_soc=0.65,
        constraints=Constraints(export_limit=30.0, soc_min=0.1, soc_max=0.9),
    ),

    # ── 여름 정오: 냉방 부하 + 최대 태양광
    "summer_noon": dict(
        price=[0.04, 0.04, 0.04, 0.04, 0.05, 0.06,
               0.08, 0.10, 0.12, 0.13, 0.13, 0.12,
               0.11, 0.12, 0.14, 0.16, 0.18, 0.17,
               0.14, 0.11, 0.08, 0.06, 0.05, 0.04],
        load=[22, 20, 19, 19, 20, 23, 30, 38, 45, 52, 58, 62,
              65, 63, 60, 58, 62, 65, 60, 52, 44, 36, 28, 23],
        generation=[0, 0, 0, 0, 0, 2, 8, 20, 36, 50, 60, 65,
                    67, 63, 56, 45, 30, 15, 4, 1, 0, 0, 0, 0],
        ess_soc=0.45,
        constraints=Constraints(export_limit=60.0, soc_min=0.1, soc_max=0.9),
    ),
}


# ─────────────────────────────────────────────────────────────────────────────
# Factory functions
# ─────────────────────────────────────────────────────────────────────────────


def make_state(scenario: ScenarioName) -> EnergyState:
    """Return a pre-built EnergyState for the given scenario name."""
    data = SCENARIOS[scenario]
    return EnergyState(
        price=data["price"],
        load=data["load"],
        generation=data["generation"],
        ess_soc=data["ess_soc"],
        constraints=data["constraints"],
        timestamp=f"2026-03-22T{list(SCENARIOS.keys()).index(scenario):02d}:00:00+00:00",
    )


class ScenarioFactory:
    """Convenience class: ScenarioFactory.<name>() → EnergyState."""

    @staticmethod
    def peak_hours() -> EnergyState:
        return make_state("peak_hours")

    @staticmethod
    def off_peak() -> EnergyState:
        return make_state("off_peak")

    @staticmethod
    def solar_peak() -> EnergyState:
        return make_state("solar_peak")

    @staticmethod
    def low_soc() -> EnergyState:
        return make_state("low_soc")

    @staticmethod
    def high_soc() -> EnergyState:
        return make_state("high_soc")

    @staticmethod
    def export_constrained() -> EnergyState:
        return make_state("export_constrained")

    @staticmethod
    def price_spike() -> EnergyState:
        return make_state("price_spike")

    @staticmethod
    def cloudy_day() -> EnergyState:
        return make_state("cloudy_day")

    @staticmethod
    def winter_morning() -> EnergyState:
        return make_state("winter_morning")

    @staticmethod
    def summer_noon() -> EnergyState:
        return make_state("summer_noon")

    @staticmethod
    def random(seed: int | None = None, horizon: int = 24) -> EnergyState:
        """Generate a random (but reproducible with seed) EnergyState."""
        rng = random.Random(seed)

        price = [round(max(0.01, rng.gauss(0.10, 0.04)), 4) for _ in range(horizon)]
        load = [round(max(1.0, rng.gauss(35.0, 10.0)), 2) for _ in range(horizon)]
        gen = [
            round(max(0.0, 40 * math.exp(-((i - horizon // 2) ** 2) / (2 * (horizon // 6) ** 2))
                      + rng.gauss(0, 2)), 2)
            for i in range(horizon)
        ]
        soc = round(rng.uniform(0.15, 0.85), 2)
        export_lim = rng.choice([0.0, 20.0, 50.0])

        return EnergyState(
            price=price,
            load=load,
            generation=gen,
            ess_soc=soc,
            constraints=Constraints(export_limit=export_lim, soc_min=0.1, soc_max=0.9),
            timestamp="2026-03-22T00:00:00+00:00",
        )

    @staticmethod
    def all_scenarios() -> list[tuple[str, EnergyState]]:
        """Return (name, state) pairs for all named scenarios."""
        return [(name, make_state(name)) for name in SCENARIOS]  # type: ignore[arg-type]


# ─────────────────────────────────────────────────────────────────────────────
# Strategy factories
# ─────────────────────────────────────────────────────────────────────────────


def make_strategy(
    *,
    charge: float = 0.0,
    discharge: float = 0.0,
    curtailment: float = 0.0,
    shift_kw: float = 0.0,
    shift_intervals: int = 0,
    market_qty: float = 0.0,
    market_price: float = 0.0,
    bid: float = 0.0,
    mode: str = "test",
) -> Strategy:
    """Build a Strategy with explicit setpoints (for unit tests)."""
    import uuid

    return Strategy(
        id=str(uuid.uuid4()),
        ess=ESSAction(charge_rate=charge, discharge_rate=discharge),
        pv=PVAction(curtailment_ratio=curtailment),
        load=LoadAction(shift_amount=shift_kw, shift_intervals=shift_intervals),
        market=MarketBid(quantity=market_qty, price=market_price),
        bid=bid,
        metadata={"mode": mode},
    )


# Pre-built strategy fixtures
STRATEGY_FIXTURES: dict[str, dict] = {
    "aggressive_discharge": dict(discharge=45.0, market_qty=40.0, market_price=0.18, bid=2.5),
    "solar_first":          dict(charge=20.0, bid=1.2),
    "load_shifting":        dict(shift_kw=8.0, shift_intervals=2, bid=0.8),
    "ess_charging":         dict(charge=30.0, bid=0.5),
    "conservative":         dict(bid=0.1),
    "soc_violation":        dict(discharge=95.0, bid=-5.0),   # violates SOC min
    "export_violation":     dict(discharge=80.0, market_qty=80.0, bid=3.0),  # exceeds export limit
}


def make_strategy_fixture(name: str) -> Strategy:
    """Return a pre-built test strategy by name."""
    return make_strategy(**STRATEGY_FIXTURES[name], mode=name)
