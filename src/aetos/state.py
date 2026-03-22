"""Core domain models and LangGraph workflow state."""

from __future__ import annotations

import operator
from typing import Annotated, Any, Optional, TypedDict

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Domain models
# ---------------------------------------------------------------------------


class Constraints(BaseModel):
    export_limit: float = 0.0  # kW; 0 = no export allowed
    soc_min: float = 0.1
    soc_max: float = 0.9


class EnergyState(BaseModel):
    """Current snapshot of the energy system (from SCADA / sensors)."""

    price: list[float] = Field(default_factory=list)       # $/kWh per interval
    load: list[float] = Field(default_factory=list)        # kW per interval
    generation: list[float] = Field(default_factory=list)  # kW (solar PV)
    ess_soc: float = 0.5                                    # state-of-charge [0, 1]
    constraints: Constraints = Field(default_factory=Constraints)
    timestamp: str = ""


class ESSAction(BaseModel):
    charge_rate: float = 0.0     # kW (positive = charging)
    discharge_rate: float = 0.0  # kW (positive = discharging)


class PVAction(BaseModel):
    curtailment_ratio: float = 0.0  # [0, 1]; 0 = full generation


class LoadAction(BaseModel):
    shift_amount: float = 0.0    # kW to shift
    shift_intervals: int = 0     # how many intervals to defer


class MarketBid(BaseModel):
    quantity: float = 0.0  # kW
    price: float = 0.0     # $/kWh


class Strategy(BaseModel):
    """A candidate energy management strategy with an associated bid value."""

    id: str
    ess: ESSAction = Field(default_factory=ESSAction)
    pv: PVAction = Field(default_factory=PVAction)
    load: LoadAction = Field(default_factory=LoadAction)
    market: MarketBid = Field(default_factory=MarketBid)
    bid: float = 0.0                         # expected reward (used in CDA)
    metadata: dict[str, Any] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# LangGraph workflow state (TypedDict with reducers)
# ---------------------------------------------------------------------------


class WorkflowState(TypedDict):
    """State object threaded through the LangGraph workflow.

    - `strategies` / `optimized` / `selected` / `reward` are SET by their
      respective nodes (last-writer wins).
    - `messages` / `step_events` use operator.add so each node appends.
    """

    energy_state: EnergyState
    services: dict[str, Any]
    strategies: list[Strategy]        # produced by StrategyGenerator
    optimized: list[Strategy]         # produced by Optimizer
    selected: Optional[Strategy]      # produced by MetaCritic (after CDA)
    reward: float
    messages: Annotated[list[str], operator.add]
    step_events: Annotated[list[dict], operator.add]  # structured per-node data for UI
