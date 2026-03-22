"""Abstract base class shared by all AETOS agents."""

from abc import ABC, abstractmethod

from ..state import EnergyState


class BaseAgent(ABC):
    """
    All agents implement a four-phase loop:

        perceive → reason → act → reflect

    ``perceive`` stores the current state and extracts a context summary.
    ``reason`` uses that context to produce a decision rationale.
    ``act``    returns the agent's output (strategies / optimized list / selection).
    ``reflect`` updates the agent's internal knowledge based on the outcome.
    """

    def __init__(self, name: str) -> None:
        self.name = name
        self._state: EnergyState | None = None
        self._context: dict = {}

    # ------------------------------------------------------------------
    # perceive
    # ------------------------------------------------------------------
    def perceive(self, state: EnergyState) -> None:
        """Store state and extract a compact context dict."""
        self._state = state
        self._context = self._extract_context(state)

    def _extract_context(self, state: EnergyState) -> dict:
        def avg(lst: list[float]) -> float:
            return sum(lst) / len(lst) if lst else 0.0

        return {
            "avg_price": avg(state.price),
            "peak_price": max(state.price, default=0.0),
            "min_price": min(state.price, default=0.0),
            "avg_load": avg(state.load),
            "avg_gen": avg(state.generation),
            "ess_soc": state.ess_soc,
            "soc_headroom": state.constraints.soc_max - state.ess_soc,
            "soc_margin": state.ess_soc - state.constraints.soc_min,
            "export_limit": state.constraints.export_limit,
        }

    # ------------------------------------------------------------------
    # reason
    # ------------------------------------------------------------------
    def reason(self) -> dict:
        """Return the current decision context.  Subclasses may override
        to incorporate LLM calls or rule-based heuristics."""
        return self._context

    # ------------------------------------------------------------------
    # act  (must be implemented)
    # ------------------------------------------------------------------
    @abstractmethod
    def act(self, *args, **kwargs):
        ...

    # ------------------------------------------------------------------
    # reflect
    # ------------------------------------------------------------------
    def reflect(self, result) -> None:
        """Called after the action is executed.  Subclasses may log,
        update internal models, or trigger learning here."""
