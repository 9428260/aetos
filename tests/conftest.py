"""pytest fixtures – shared across all test modules."""

import pytest

from aetos.state import Constraints, EnergyState

from .factories import ScenarioFactory, make_state, make_strategy_fixture


# ─────────────────────────────────────────────────────────────────────────────
# EnergyState fixtures
# ─────────────────────────────────────────────────────────────────────────────


@pytest.fixture()
def sample_state() -> EnergyState:
    return EnergyState(
        price=[0.05, 0.06, 0.12, 0.15, 0.10, 0.07] * 4,
        load=[25.0, 30.0, 40.0, 45.0, 35.0, 20.0] * 4,
        generation=[0.0, 0.0, 5.0, 20.0, 30.0, 10.0] * 4,
        ess_soc=0.5,
        constraints=Constraints(export_limit=50.0, soc_min=0.1, soc_max=0.9),
    )


@pytest.fixture()
def state_peak_hours() -> EnergyState:
    """피크 시간대: 높은 가격, 높은 부하, 보통 태양광."""
    return ScenarioFactory.peak_hours()


@pytest.fixture()
def state_off_peak() -> EnergyState:
    """오프피크 심야: 낮은 가격, 낮은 부하, 발전 없음."""
    return ScenarioFactory.off_peak()


@pytest.fixture()
def state_solar_peak() -> EnergyState:
    """태양광 최대: 맑은 날 정오, 과잉 발전 처리 필요."""
    return ScenarioFactory.solar_peak()


@pytest.fixture()
def state_low_soc() -> EnergyState:
    """저 SOC: ESS 거의 방전 (0.12), 충전 전략 선호."""
    return ScenarioFactory.low_soc()


@pytest.fixture()
def state_high_soc() -> EnergyState:
    """고 SOC: ESS 거의 충전 (0.88), 방전 전략 선호."""
    return ScenarioFactory.high_soc()


@pytest.fixture()
def state_export_constrained() -> EnergyState:
    """수출 제약: 계통 역조류 5kW 엄격 제한."""
    return ScenarioFactory.export_constrained()


@pytest.fixture()
def state_price_spike() -> EnergyState:
    """가격 급등: 08–11시 0.40–0.60 $/kWh 급등 이벤트."""
    return ScenarioFactory.price_spike()


@pytest.fixture()
def state_cloudy_day() -> EnergyState:
    """흐린 날: 태양광 출력 낮음 (최대 14kW)."""
    return ScenarioFactory.cloudy_day()


@pytest.fixture()
def state_winter_morning() -> EnergyState:
    """겨울 아침: 낮은 발전 + 높은 난방 부하."""
    return ScenarioFactory.winter_morning()


@pytest.fixture()
def state_summer_noon() -> EnergyState:
    """여름 정오: 냉방 부하 + 최대 태양광 (67kW)."""
    return ScenarioFactory.summer_noon()


@pytest.fixture()
def state_random_seed42() -> EnergyState:
    """재현 가능한 랜덤 상태 (seed=42)."""
    return ScenarioFactory.random(seed=42)


@pytest.fixture(
    params=[
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
)
def all_states(request) -> EnergyState:
    """Parametrised fixture: runs a test once per scenario."""
    return make_state(request.param)


# ─────────────────────────────────────────────────────────────────────────────
# Strategy fixtures
# ─────────────────────────────────────────────────────────────────────────────


@pytest.fixture()
def strategy_aggressive_discharge():
    return make_strategy_fixture("aggressive_discharge")


@pytest.fixture()
def strategy_solar_first():
    return make_strategy_fixture("solar_first")


@pytest.fixture()
def strategy_load_shifting():
    return make_strategy_fixture("load_shifting")


@pytest.fixture()
def strategy_ess_charging():
    return make_strategy_fixture("ess_charging")


@pytest.fixture()
def strategy_conservative():
    return make_strategy_fixture("conservative")


@pytest.fixture()
def strategy_soc_violation():
    """SOC 제약 위반 전략 (MetaCritic이 필터해야 함)."""
    return make_strategy_fixture("soc_violation")


@pytest.fixture()
def strategy_export_violation():
    """수출 제약 위반 전략 (MetaCritic이 필터해야 함)."""
    return make_strategy_fixture("export_violation")
