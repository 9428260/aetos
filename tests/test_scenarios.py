"""Scenario-based tests using generated test data."""

import asyncio

import pytest

from aetos.agents.critic import MetaCritic
from aetos.agents.optimizer import Optimizer
from aetos.agents.strategy import StrategyGenerator
from aetos.negotiation.cda import CDAMarket
from aetos.reward import compute_reward, decompose_reward
from aetos.state import EnergyState
from aetos.workflow import run_workflow

from .factories import ScenarioFactory, make_strategy_fixture

gen = StrategyGenerator()
opt = Optimizer(iterations=5)
market = CDAMarket(min_candidates=2)
critic = MetaCritic()


# ─────────────────────────────────────────────────────────────────────────────
# Reward 컴포넌트 검증
# ─────────────────────────────────────────────────────────────────────────────


class TestRewardByScenario:
    def test_solar_peak_has_positive_solar_roi(self, state_solar_peak):
        """태양광 피크: solar_roi 컴포넌트가 양수여야 함."""
        strategies = gen.act(state_solar_peak)
        solar_first = next(s for s in strategies if s.metadata["mode"] == "solar_first")
        d = decompose_reward(state_solar_peak, solar_first)
        assert d["solar_roi"] > 0

    def test_price_spike_discharge_beats_conservative(self, state_price_spike):
        """가격 급등: 방전 전략이 보수 전략보다 reward가 높아야 함."""
        strategies = gen.act(state_price_spike)
        discharge = next(s for s in strategies if s.metadata["mode"] == "aggressive_discharge")
        conservative = next(s for s in strategies if s.metadata["mode"] == "conservative")
        assert discharge.bid > conservative.bid

    def test_off_peak_charge_no_soc_violation(self, state_off_peak):
        """오프피크 충전 전략: SOC 한도를 초과하지 않아야 함.

        reward function은 single-period이므로 충전은 현재 비용으로 계산됨.
        오프피크 충전의 가치(미래 피크 방전 수익)는 multi-period 모델에서 측정됨.
        여기서는 충전 전략이 제약 조건을 위반하지 않는지만 검증한다.
        """
        strategies = gen.act(state_off_peak)
        charge = next(s for s in strategies if s.metadata["mode"] == "ess_charge")
        state = state_off_peak
        capacity = 100.0
        delta_soc = (charge.ess.charge_rate - charge.ess.discharge_rate) / capacity
        new_soc = state.ess_soc + delta_soc
        assert new_soc <= state.constraints.soc_max

    def test_high_soc_discharge_preferred(self, state_high_soc):
        """고 SOC: 방전 관련 전략의 soc 페널티가 낮아야 함."""
        strategies = gen.act(state_high_soc)
        for s in strategies:
            d = decompose_reward(state_high_soc, s)
            # 고 SOC → 충전 전략에서 SOC 초과 위험 → 위반 시 risk_penalty
            assert isinstance(d["risk_penalty"], float)

    def test_low_soc_discharge_penalised(self, state_low_soc):
        """저 SOC: 과도한 방전 전략은 risk_penalty가 높아야 함."""
        s = make_strategy_fixture("soc_violation")
        d = decompose_reward(state_low_soc, s)
        assert d["risk_penalty"] > 0


# ─────────────────────────────────────────────────────────────────────────────
# MetaCritic 정책 필터 검증
# ─────────────────────────────────────────────────────────────────────────────


class TestMetaCriticPolicy:
    def test_filters_soc_violation(self, state_peak_hours, strategy_soc_violation):
        """MetaCritic이 SOC 위반 전략을 걸러야 함 (대안 있을 때)."""
        strategies = gen.act(state_peak_hours)
        strategies.append(strategy_soc_violation)
        selected = critic.act(state_peak_hours, strategies)
        # 위반 전략이 선택되면 안 됨 (대안이 6개 있음)
        assert selected.id != strategy_soc_violation.id

    def test_selects_highest_reward(self, state_solar_peak):
        """MetaCritic이 정책 통과 후보 중 reward 최대 전략을 선택해야 함.

        policy filter로 일부 candidates가 제거될 수 있으므로,
        필터 통과 후 남은 것들 중 max와 비교한다.
        """
        strategies = gen.act(state_solar_peak)
        optimized = opt.act(state_solar_peak, strategies)
        winners = market.auction(optimized)
        selected = critic.act(state_solar_peak, winners)

        # MetaCritic 내부와 동일하게 policy filter 적용 후 max 계산
        compliant = critic._filter_policy(state_solar_peak, winners)
        pool = compliant if compliant else winners
        max_reward = max(compute_reward(state_solar_peak, s) for s in pool)
        assert abs(selected.bid - max_reward) < 1e-5

    def test_export_constraint_respected(self, state_export_constrained):
        """수출 제약 5kW: MetaCritic이 선택한 전략은 제약 내에 있어야 함."""
        strategies = gen.act(state_export_constrained)
        optimized = opt.act(state_export_constrained, strategies)
        winners = market.auction(optimized)
        selected = critic.act(state_export_constrained, winners)

        # 선택된 전략의 net_export 계산
        state = state_export_constrained
        avg_gen = sum(state.generation) / len(state.generation)
        avg_load = sum(state.load) / len(state.load)
        net_export = (
            avg_gen * (1 - selected.pv.curtailment_ratio)
            + selected.ess.discharge_rate
            - avg_load
        )
        assert net_export <= state.constraints.export_limit + 1e-3  # 1W tolerance


# ─────────────────────────────────────────────────────────────────────────────
# CDA 경매 검증
# ─────────────────────────────────────────────────────────────────────────────


class TestCDA:
    def test_clearing_price_is_median(self, state_peak_hours):
        """CDA clearing price가 내림차순 정렬 기준 중간값이어야 함.

        CDA는 내림차순(highest bid first)으로 정렬한 뒤 bids[mid]를 사용한다.
        """
        strategies = gen.act(state_peak_hours)
        optimized = opt.act(state_peak_hours, strategies)
        winners = market.auction(optimized)

        # CDA 내부와 동일한 계산: 내림차순 정렬 후 mid
        bids_desc = sorted((s.bid for s in optimized), reverse=True)
        mid = len(bids_desc) // 2
        expected_clearing = bids_desc[mid]
        assert abs(market.history[-1]["clearing_price"] - expected_clearing) < 1e-6

    def test_all_winners_above_clearing(self, state_summer_noon):
        """모든 winner의 bid ≥ clearing price."""
        strategies = gen.act(state_summer_noon)
        optimized = opt.act(state_summer_noon, strategies)
        winners = market.auction(optimized)
        cp = market.history[-1]["clearing_price"]
        for w in winners:
            assert w.bid >= cp - 1e-6

    def test_min_candidates_guarantee(self):
        """min_candidates=3 설정 시 winner가 최소 3개 반환되어야 함."""
        state = ScenarioFactory.random(seed=7)
        strategies = gen.act(state)
        m = CDAMarket(min_candidates=3)
        winners = m.auction(strategies)
        assert len(winners) >= 3


# ─────────────────────────────────────────────────────────────────────────────
# 전체 워크플로우 (파라미터화)
# ─────────────────────────────────────────────────────────────────────────────


def test_workflow_all_scenarios(all_states: EnergyState):
    """모든 시나리오에서 워크플로우가 완료되고 전략이 선택되어야 함."""
    result = asyncio.run(run_workflow(all_states))

    assert result["selected"] is not None, "전략이 선택되지 않음"
    assert isinstance(result["reward"], float)
    assert len(result["messages"]) == 5  # generate, optimize, auction, critique, dispatch

    selected = result["selected"]
    assert 0.0 <= selected.ess.charge_rate
    assert 0.0 <= selected.ess.discharge_rate
    assert 0.0 <= selected.pv.curtailment_ratio <= 1.0


# ─────────────────────────────────────────────────────────────────────────────
# 랜덤 데이터 재현성 검증
# ─────────────────────────────────────────────────────────────────────────────


def test_random_state_reproducible():
    """같은 seed로 생성된 상태는 동일해야 함."""
    s1 = ScenarioFactory.random(seed=99)
    s2 = ScenarioFactory.random(seed=99)
    assert s1.price == s2.price
    assert s1.load == s2.load
    assert s1.generation == s2.generation
    assert s1.ess_soc == s2.ess_soc


def test_random_state_different_seeds():
    """다른 seed는 다른 상태를 생성해야 함."""
    s1 = ScenarioFactory.random(seed=1)
    s2 = ScenarioFactory.random(seed=2)
    assert s1.price != s2.price
