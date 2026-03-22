"""Shared runtime services for workflow, MCP, and deepagents integrations."""

from __future__ import annotations

import random
import threading
from datetime import datetime
from typing import Any

from .a2a import build_local_broker
from .a2a.runtime import A2AProtocolError
from .config import settings
from .a2a import build_local_broker
from .agents.critic import MetaCritic
from .agents.optimizer import Optimizer
from .agents.strategy import StrategyGenerator
from .execution.dispatch import Dispatcher
from .negotiation.cda import CDAMarket
from .observability import audit_log, metrics, timed
from .reward import compute_reward, decompose_reward
from .state import Constraints, EnergyState, Strategy


class RuntimeSession:
    def __init__(self, dispatcher: Dispatcher) -> None:
        self.strategy_gen = StrategyGenerator()
        self.optimizer = Optimizer()
        self.market = CDAMarket(min_candidates=2)
        self.critic = MetaCritic()
        self.dispatcher = dispatcher
        self.broker = build_local_broker(
            self.strategy_gen,
            self.optimizer,
            self.critic,
            self.dispatcher,
        )


class AetosRuntime:
    def __init__(self) -> None:
        self.dispatcher = Dispatcher()
        self._lock = threading.RLock()

    def new_session(self) -> RuntimeSession:
        transport = settings.a2a_transport.strip().lower()
        if transport != "local":
            raise A2AProtocolError(
                f"remote A2A is not enabled in this deployment (A2A_TRANSPORT={transport!r})"
            )
        return RuntimeSession(self.dispatcher)

    def forecast(self, horizon: int = 24) -> dict:
        with timed("runtime.forecast", audit_event="runtime.forecast"):
            hour_now = datetime.now().hour
            price, load, generation = [], [], []

            for i in range(horizon):
                h = (hour_now + i) % 24
                price.append(round(0.04 + 0.06 * (9 <= h <= 18) + random.gauss(0, 0.005), 4))
                load.append(round(max(0, 20 + 15 * (8 <= h <= 21) + random.gauss(0, 2)), 2))
                generation.append(round(max(0, 30 * (1 - abs(h - 13) / 8) + random.gauss(0, 1)), 2))

            return {"price": price, "load": load, "generation": generation}

    def optimize_via_a2a(self, state: EnergyState) -> dict:
        with self._lock, timed("runtime.optimize", audit_event="runtime.optimize"):
            session = self.new_session()
            generated = session.broker.send_task(
                agent="strategy-generator",
                skill="generate_strategies",
                input={"energy_state": state.model_dump()},
            )
            strategies = [
                Strategy.model_validate(s) for s in generated.artifacts[0].data["strategies"]
            ]

            optimized_result = session.broker.send_task(
                agent="optimizer",
                skill="optimize_strategies",
                input={
                    "energy_state": state.model_dump(),
                    "strategies": [s.model_dump() for s in strategies],
                },
            )
            optimized = [
                Strategy.model_validate(s) for s in optimized_result.artifacts[0].data["strategies"]
            ]

            winners = session.market.auction(optimized)
            selected_result = session.broker.send_task(
                agent="meta-critic",
                skill="select_strategy",
                input={
                    "energy_state": state.model_dump(),
                    "candidates": [s.model_dump() for s in winners],
                },
            )
            selected = Strategy.model_validate(selected_result.artifacts[0].data["selected"])
            reward = float(selected_result.artifacts[0].data["reward"])

            result = selected.model_dump()
            result["reward"] = reward
            result["reward_decomposition"] = decompose_reward(state, selected)
            return result

    def policy_check(self, strategy: Strategy, state: EnergyState) -> dict:
        c: Constraints = state.constraints
        violations: list[str] = []

        if strategy.ess.charge_rate < 0:
            violations.append("ESS charge_rate must be non-negative")
        if strategy.ess.discharge_rate < 0:
            violations.append("ESS discharge_rate must be non-negative")
        if not (0.0 <= strategy.pv.curtailment_ratio <= 1.0):
            violations.append("PV curtailment_ratio must be in [0, 1]")

        capacity = 100.0
        delta_soc = (strategy.ess.charge_rate - strategy.ess.discharge_rate) / capacity
        new_soc = state.ess_soc + delta_soc

        if new_soc < c.soc_min:
            violations.append(f"New SOC {new_soc:.3f} < soc_min {c.soc_min}")
        if new_soc > c.soc_max:
            violations.append(f"New SOC {new_soc:.3f} > soc_max {c.soc_max}")

        if c.export_limit > 0:
            avg_gen = sum(state.generation) / len(state.generation) if state.generation else 0.0
            avg_load = sum(state.load) / len(state.load) if state.load else 0.0
            net_export = (
                avg_gen * (1 - strategy.pv.curtailment_ratio)
                + strategy.ess.discharge_rate
                - avg_load
            )
            if net_export > c.export_limit:
                violations.append(
                    f"Net export {net_export:.1f} kW exceeds limit {c.export_limit} kW"
                )

        return {"compliant": len(violations) == 0, "violations": violations}

    def dispatch_via_a2a(
        self,
        strategy: Strategy,
        state: EnergyState | None = None,
        dry_run: bool = True,
        *,
        idempotency_key: str | None = None,
    ) -> dict:
        with self._lock, timed("runtime.dispatch", audit_event="runtime.dispatch", dry_run=dry_run):
            energy = state or EnergyState()
            policy = self.policy_check(strategy, energy)
            if not policy["compliant"]:
                raise RuntimeError("dispatch blocked by policy violations")

            session = self.new_session()
            dispatch_result = session.broker.send_task(
                agent="dispatcher",
                skill="dispatch_strategy",
                input={
                    "energy_state": energy.model_dump(),
                    "strategy": strategy.model_dump(),
                    "dry_run": dry_run,
                    "idempotency_key": idempotency_key,
                },
            )
            action = dict(dispatch_result.artifacts[0].data["action"])
            return action

    def kpi(self) -> dict:
        log = self.dispatcher.get_log()
        if not log:
            return {
                "cost_saving": 0.0,
                "ess_profit": 0.0,
                "solar_roi": 0.0,
                "total_reward": 0.0,
                "n_dispatches": 0,
            }

        total_reward = sum(entry.get("expected_reward", 0.0) for entry in log)
        decomps = [entry.get("reward_decomposition", {}) for entry in log]
        cost_saving = sum(d.get("cost_saving", 0.0) for d in decomps)
        ess_profit = sum(d.get("ess_profit", 0.0) for d in decomps)
        solar_roi = sum(d.get("solar_roi", 0.0) for d in decomps)

        return {
            "cost_saving": round(cost_saving, 4),
            "ess_profit": round(ess_profit, 4),
            "solar_roi": round(solar_roi, 4),
            "total_reward": round(total_reward, 4),
            "n_dispatches": len(log),
            "last_dispatch": log[-1]["timestamp"],
        }

    def compute_reward(self, state: EnergyState, strategy: Strategy) -> float:
        return compute_reward(state, strategy)

    def a2a_policy(self) -> dict[str, Any]:
        return {
            "transport": settings.a2a_transport,
            "remote_endpoint": settings.a2a_remote_endpoint,
            "remote_enabled": settings.a2a_transport.strip().lower() == "remote",
            "policy": "local-only transport is enforced unless explicitly configured otherwise",
        }

    def agent_cards(self) -> list[dict[str, Any]]:
        session = self.new_session()
        return [card.model_dump() for card in session.broker.agent_cards()]


runtime = AetosRuntime()
