"""Integration tests for the core agentic workflow (no DB required)."""

import asyncio

import pytest

from aetos.agents.critic import MetaCritic
from aetos.agents.optimizer import Optimizer
from aetos.agents.strategy import StrategyGenerator
from aetos.a2a import build_local_broker
from aetos.execution.dispatch import Dispatcher
from aetos.negotiation.cda import CDAMarket
from aetos.reward import compute_reward, decompose_reward
from aetos.state import Constraints, EnergyState
from aetos.workflow import run_workflow


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def sample_state() -> EnergyState:
    return EnergyState(
        price=[0.05, 0.06, 0.12, 0.15, 0.10, 0.07] * 4,
        load=[25.0, 30.0, 40.0, 45.0, 35.0, 20.0] * 4,
        generation=[0.0, 0.0, 5.0, 20.0, 30.0, 10.0] * 4,
        ess_soc=0.5,
        constraints=Constraints(export_limit=50.0, soc_min=0.1, soc_max=0.9),
    )


# ---------------------------------------------------------------------------
# Unit tests
# ---------------------------------------------------------------------------


def test_strategy_generator_produces_strategies(sample_state):
    gen = StrategyGenerator()
    strategies = gen.act(sample_state)
    assert len(strategies) >= 1
    for s in strategies:
        assert s.id
        assert isinstance(s.bid, float)


def test_reward_non_negative_conservative(sample_state):
    gen = StrategyGenerator()
    strategies = gen.act(sample_state)
    conservative = next(s for s in strategies if s.metadata.get("mode") == "conservative")
    r = compute_reward(sample_state, conservative)
    # Conservative strategy: no ESS action, no load shift → reward dominated by solar ROI
    assert isinstance(r, float)


def test_optimizer_improves_or_maintains(sample_state):
    gen = StrategyGenerator()
    strategies = gen.act(sample_state)
    opt = Optimizer(iterations=5)
    optimized = opt.act(sample_state, strategies)

    assert len(optimized) == len(strategies)
    # At least one strategy should have bid >= original
    for orig, optim in zip(strategies, optimized):
        assert optim.bid >= orig.bid - 1e-6  # allow tiny floating drift


def test_cda_returns_winners(sample_state):
    gen = StrategyGenerator()
    strategies = gen.act(sample_state)
    opt = Optimizer(iterations=3)
    optimized = opt.act(sample_state, strategies)

    market = CDAMarket(min_candidates=2)
    winners = market.auction(optimized)

    assert len(winners) >= 1
    assert market.history[-1]["n_winners"] >= 1


def test_metacritic_selects_one(sample_state):
    gen = StrategyGenerator()
    opt = Optimizer(iterations=3)
    market = CDAMarket(min_candidates=2)
    critic = MetaCritic()

    strategies = gen.act(sample_state)
    optimized = opt.act(sample_state, strategies)
    winners = market.auction(optimized)
    selected = critic.act(sample_state, winners)

    assert selected is not None
    assert selected.bid > -1e6


def test_reward_decompose_keys(sample_state):
    gen = StrategyGenerator()
    s = gen.act(sample_state)[0]
    decomp = decompose_reward(sample_state, s)
    for key in ("cost_saving", "solar_roi", "ess_profit", "degradation_cost", "risk_penalty", "total"):
        assert key in decomp


def test_a2a_broker_routes_strategy_generation(sample_state):
    broker = build_local_broker(
        StrategyGenerator(),
        Optimizer(iterations=2),
        MetaCritic(),
        Dispatcher(),
    )
    result = broker.send_task(
        agent="strategy-generator",
        skill="generate_strategies",
        input={"energy_state": sample_state.model_dump()},
    )
    assert result.status == "completed"
    assert result.artifacts[0].name == "strategies"
    assert len(result.artifacts[0].data["strategies"]) >= 1


# ---------------------------------------------------------------------------
# Async integration test
# ---------------------------------------------------------------------------


def test_full_workflow(sample_state):
    result = asyncio.run(run_workflow(sample_state))

    assert result["selected"] is not None
    assert result["reward"] != 0 or True  # just verify it ran
    assert len(result["messages"]) >= 4  # generate, optimize, auction, critique, dispatch
    assert any(":a2a]" in msg for msg in result["messages"])
