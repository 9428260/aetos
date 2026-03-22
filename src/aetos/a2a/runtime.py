"""Local A2A runtime for routing tasks between AETOS agents."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from .protocol import A2AAgentCard, A2AMessage, A2ATask, A2ATaskResult


class A2AProtocolError(RuntimeError):
    """Raised when an A2A task cannot be routed or is malformed."""


TaskHandler = Callable[[A2ATask], A2ATaskResult]


class LocalA2ABroker:
    """In-process broker implementing a small subset of A2A task routing."""

    def __init__(self) -> None:
        self._handlers: dict[str, TaskHandler] = {}
        self._cards: dict[str, A2AAgentCard] = {}

    def register(self, card: A2AAgentCard, handler: TaskHandler) -> None:
        self._cards[card.name] = card
        self._handlers[card.name] = handler

    def agent_cards(self) -> list[A2AAgentCard]:
        return list(self._cards.values())

    def send_task(
        self,
        *,
        agent: str,
        skill: str,
        input: dict[str, Any],
        metadata: dict[str, Any] | None = None,
    ) -> A2ATaskResult:
        handler = self._handlers.get(agent)
        if handler is None:
            raise A2AProtocolError(f"unknown agent '{agent}'")

        task = A2ATask(
            agent=agent,
            skill=skill,
            input=input,
            metadata=metadata or {},
            message=A2AMessage(
                role="requester",
                parts=[{"kind": "text", "text": f"Execute skill '{skill}'"}],
            ),
        )
        result = handler(task)
        if result.task_id != task.id:
            raise A2AProtocolError("task/result id mismatch")
        return result
