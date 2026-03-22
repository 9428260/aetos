"""Tests for the MCP tool layer."""

from aetos.mcp import server as mcp_server
from aetos.runtime import runtime
from aetos.state import Strategy


def test_mcp_optimize_delegates_to_runtime(sample_state, monkeypatch):
    expected = {"id": "strategy-1", "reward": 1.23, "reward_decomposition": {"total": 1.23}}
    called = {}

    def fake_optimize(state):
        called["state"] = state
        return expected

    monkeypatch.setattr(runtime, "optimize_via_a2a", fake_optimize)

    result = mcp_server.optimize(sample_state.model_dump())

    assert result == expected
    assert called["state"].model_dump() == sample_state.model_dump()


def test_mcp_dispatch_delegates_to_runtime(sample_state, monkeypatch):
    strategy = Strategy(
        id="dispatch-1",
        bid=1.0,
        metadata={"mode": "test"},
    )
    called = {}

    def fake_dispatch(strategy_arg, state_arg, dry_run, idempotency_key=None):
        called["strategy"] = strategy_arg
        called["state"] = state_arg
        called["dry_run"] = dry_run
        called["idempotency_key"] = idempotency_key
        return {"ok": True, "dry_run": dry_run}

    monkeypatch.setattr(runtime, "dispatch_via_a2a", fake_dispatch)

    result = mcp_server.dispatch(strategy.model_dump(), sample_state.model_dump(), dry_run=False)

    assert result == {"ok": True, "dry_run": False}
    assert called["strategy"].id == "dispatch-1"
    assert called["state"].model_dump() == sample_state.model_dump()
    assert called["dry_run"] is False


def test_mcp_policy_check_flags_violation(sample_state):
    violating = Strategy(
        id="bad-1",
        bid=0.0,
        ess={"charge_rate": 0.0, "discharge_rate": 100.0},
        metadata={"mode": "violation"},
    )

    result = mcp_server.policy_check(violating.model_dump(), sample_state.model_dump())

    assert result["compliant"] is False
    assert result["violations"]


def test_mcp_kpi_includes_dispatches(sample_state):
    before = runtime.kpi()["n_dispatches"]
    optimized = mcp_server.optimize(sample_state.model_dump())
    action = mcp_server.dispatch(optimized, sample_state.model_dump(), dry_run=True)
    after = mcp_server.kpi()

    assert action["dry_run"] is True
    assert after["n_dispatches"] >= before + 1
