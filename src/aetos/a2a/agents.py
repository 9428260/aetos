"""A2A adapters for the core AETOS agents."""

from __future__ import annotations

from typing import Any

from ..agents.critic import MetaCritic
from ..agents.optimizer import Optimizer
from ..agents.strategy import StrategyGenerator
from ..execution.dispatch import Dispatcher
from ..reward import compute_reward
from ..state import EnergyState, Strategy
from .protocol import A2AAgentCard, A2AArtifact, A2AMessage, A2ATask, A2ATaskResult
from .runtime import A2AProtocolError, LocalA2ABroker


def _result(
    task: A2ATask,
    *,
    artifact_name: str,
    data: dict[str, Any],
    metrics: dict[str, Any] | None = None,
) -> A2ATaskResult:
    return A2ATaskResult(
        task_id=task.id,
        agent=task.agent,
        message=A2AMessage(
            role="agent",
            parts=[{"kind": "text", "text": f"{task.agent}.{task.skill} completed"}],
        ),
        artifacts=[A2AArtifact(name=artifact_name, data=data)],
        metrics=metrics or {},
    )


class StrategyGeneratorA2A:
    card = A2AAgentCard(
        name="strategy-generator",
        description="Generate candidate energy strategies",
        skills=["generate_strategies"],
    )

    def __init__(self, agent: StrategyGenerator) -> None:
        self._agent = agent

    def __call__(self, task: A2ATask) -> A2ATaskResult:
        if task.skill != "generate_strategies":
            raise A2AProtocolError(f"unsupported skill '{task.skill}'")
        energy = EnergyState.model_validate(task.input["energy_state"])
        strategies = self._agent.act(energy)
        return _result(
            task,
            artifact_name="strategies",
            data={"strategies": [s.model_dump() for s in strategies]},
            metrics={"count": len(strategies)},
        )


class OptimizerA2A:
    card = A2AAgentCard(
        name="optimizer",
        description="Refine candidate strategies",
        skills=["optimize_strategies"],
    )

    def __init__(self, agent: Optimizer) -> None:
        self._agent = agent

    def __call__(self, task: A2ATask) -> A2ATaskResult:
        if task.skill != "optimize_strategies":
            raise A2AProtocolError(f"unsupported skill '{task.skill}'")
        energy = EnergyState.model_validate(task.input["energy_state"])
        strategies = [Strategy.model_validate(s) for s in task.input["strategies"]]
        optimized = self._agent.act(energy, strategies)
        return _result(
            task,
            artifact_name="optimized",
            data={"strategies": [s.model_dump() for s in optimized]},
            metrics={"count": len(optimized), "iterations": self._agent.iterations},
        )


class CriticA2A:
    card = A2AAgentCard(
        name="meta-critic",
        description="Select the best compliant strategy",
        skills=["select_strategy"],
    )

    def __init__(self, agent: MetaCritic) -> None:
        self._agent = agent

    def __call__(self, task: A2ATask) -> A2ATaskResult:
        if task.skill != "select_strategy":
            raise A2AProtocolError(f"unsupported skill '{task.skill}'")
        energy = EnergyState.model_validate(task.input["energy_state"])
        candidates = [Strategy.model_validate(s) for s in task.input["candidates"]]
        selected = self._agent.act(energy, candidates)
        reward = compute_reward(energy, selected)
        return _result(
            task,
            artifact_name="selection",
            data={"selected": selected.model_dump(), "reward": reward},
            metrics={"count": len(candidates)},
        )


class DispatcherA2A:
    card = A2AAgentCard(
        name="dispatcher",
        description="Dispatch the selected strategy to the execution layer",
        skills=["dispatch_strategy"],
    )

    def __init__(self, agent: Dispatcher) -> None:
        self._agent = agent

    def __call__(self, task: A2ATask) -> A2ATaskResult:
        if task.skill != "dispatch_strategy":
            raise A2AProtocolError(f"unsupported skill '{task.skill}'")
        energy = EnergyState.model_validate(task.input["energy_state"])
        strategy = Strategy.model_validate(task.input["strategy"])
        action = self._agent.dispatch(energy, strategy)
        return _result(
            task,
            artifact_name="dispatch",
            data={"action": action},
        )


def build_local_broker(
    strategy_gen: StrategyGenerator,
    optimizer: Optimizer,
    critic: MetaCritic,
    dispatcher: Dispatcher,
) -> LocalA2ABroker:
    broker = LocalA2ABroker()
    broker.register(StrategyGeneratorA2A.card, StrategyGeneratorA2A(strategy_gen))
    broker.register(OptimizerA2A.card, OptimizerA2A(optimizer))
    broker.register(CriticA2A.card, CriticA2A(critic))
    broker.register(DispatcherA2A.card, DispatcherA2A(dispatcher))
    return broker
