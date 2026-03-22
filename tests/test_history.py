"""Unit tests for workflow history persistence helpers (no DB required)."""

from types import SimpleNamespace

from aetos.db.history import _kpi_values, _reward_decomposition


def test_reward_decomposition_empty() -> None:
    assert _reward_decomposition({}) == {}


def test_reward_decomposition_from_strategy() -> None:
    selected = SimpleNamespace(metadata={"reward_decomposition": {"cost_saving": 1.5}})
    assert _reward_decomposition({"selected": selected}) == {"cost_saving": 1.5}


def test_kpi_values_fallback() -> None:
    assert _kpi_values({"reward": 1.0}, {}) == (0.3, 0.3, 0.2)


def test_kpi_values_from_decomp() -> None:
    assert _kpi_values(
        {"reward": 10.0},
        {"cost_saving": 1.0, "ess_profit": 2.0, "solar_roi": 3.0},
    ) == (1.0, 2.0, 3.0)
