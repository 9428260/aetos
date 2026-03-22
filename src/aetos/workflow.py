"""
LangGraph workflow
==================

Node order:
  generate → optimize → auction (CDA) → critique (MetaCritic) → dispatch → END

Each node emits a structured `step_event` dict consumed by the UI dashboard.
"""

from __future__ import annotations

import logging
import time

from langgraph.graph import END, StateGraph

from .agents.critic import MetaCritic
from .agents.optimizer import Optimizer
from .agents.strategy import StrategyGenerator
from .execution.dispatch import Dispatcher
from .negotiation.cda import CDAMarket
from .reward import compute_reward
from .state import EnergyState, WorkflowState

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Singleton agent instances
# ---------------------------------------------------------------------------
_strategy_gen = StrategyGenerator()
_optimizer = Optimizer()
_market = CDAMarket(min_candidates=2)
_critic = MetaCritic()
_dispatcher = Dispatcher()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _strategy_info(s) -> dict:
    return {
        "id": s.id,
        "mode": s.metadata.get("mode", "unknown"),
        "bid": round(s.bid, 4),
        "ess_charge": round(s.ess.charge_rate, 2),
        "ess_discharge": round(s.ess.discharge_rate, 2),
        "pv_curtailment": round(s.pv.curtailment_ratio, 3),
        "load_shift": round(s.load.shift_amount, 2),
        "market_qty": round(s.market.quantity, 2),
        "market_price": round(s.market.price, 4),
    }


# ---------------------------------------------------------------------------
# LangGraph node functions
# ---------------------------------------------------------------------------


def node_generate(state: WorkflowState) -> dict:
    t0 = time.perf_counter()
    energy = state["energy_state"]
    strategies = _strategy_gen.act(energy)
    ms = int((time.perf_counter() - t0) * 1000)

    logger.info("generate: %d strategies  %dms", len(strategies), ms)
    return {
        "strategies": strategies,
        "messages": [f"[generate] {len(strategies)} strategies  {ms}ms"],
        "step_events": [{
            "node": "generate",
            "label": "Strategy Generation",
            "icon": "🎯",
            "status": "done",
            "duration_ms": ms,
            "summary": f"{len(strategies)} candidate strategies",
            "detail": "modes: " + ", ".join(s.metadata.get("mode", "?") for s in strategies),
            "strategies": [_strategy_info(s) for s in strategies],
        }],
    }


def node_optimize(state: WorkflowState) -> dict:
    t0 = time.perf_counter()
    energy = state["energy_state"]
    original_bids = [s.bid for s in state["strategies"]]
    optimized = _optimizer.act(energy, state["strategies"])
    ms = int((time.perf_counter() - t0) * 1000)

    improvements = [
        round((o.bid - orig) / abs(orig) * 100, 1) if orig != 0 else 0
        for o, orig in zip(optimized, original_bids)
    ]
    avg_imp = round(sum(improvements) / len(improvements), 1) if improvements else 0
    best_imp = round(max(improvements), 1) if improvements else 0

    logger.info("optimize: %d refined  %dms  avg_improvement=%.1f%%", len(optimized), ms, avg_imp)
    return {
        "optimized": optimized,
        "messages": [f"[optimize] {len(optimized)} refined  avg+{avg_imp}%  {ms}ms"],
        "step_events": [{
            "node": "optimize",
            "label": "Optimizer (Local Search)",
            "icon": "⚡",
            "status": "done",
            "duration_ms": ms,
            "summary": f"avg improvement {avg_imp:+.1f}%  best {best_imp:+.1f}%",
            "detail": f"{_optimizer.iterations} iterations per strategy",
            "strategies": [_strategy_info(s) for s in optimized],
        }],
    }


def node_auction(state: WorkflowState) -> dict:
    t0 = time.perf_counter()
    winners = _market.auction(state["optimized"])
    last = _market.history[-1]
    ms = int((time.perf_counter() - t0) * 1000)

    logger.info("auction: %d/%d cleared at %.4f  %dms",
                last["n_winners"], last["n_bids"], last["clearing_price"], ms)
    return {
        "optimized": winners,
        "messages": [
            f"[auction] clearing={last['clearing_price']:.4f}  "
            f"winners={last['n_winners']}/{last['n_bids']}  {ms}ms"
        ],
        "step_events": [{
            "node": "auction",
            "label": "CDA Auction",
            "icon": "🏛️",
            "status": "done",
            "duration_ms": ms,
            "summary": f"{last['n_winners']}/{last['n_bids']} strategies cleared",
            "detail": f"clearing price: {last['clearing_price']:.4f}  "
                      f"best bid: {last['best_bid']:.4f}",
            "clearing_price": round(last["clearing_price"], 4),
            "n_bids": last["n_bids"],
            "n_winners": last["n_winners"],
            "best_bid": round(last["best_bid"], 4),
            "worst_bid": round(last["worst_bid"], 4),
            "winners": [_strategy_info(s) for s in winners],
        }],
    }


def node_critique(state: WorkflowState) -> dict:
    t0 = time.perf_counter()
    energy = state["energy_state"]
    candidates = state["optimized"]
    selected = _critic.act(energy, candidates)
    reward = compute_reward(energy, selected)
    ms = int((time.perf_counter() - t0) * 1000)

    decomp = selected.metadata.get("reward_decomposition", {})
    n_filtered = len(candidates) - len(_critic._filter_policy(energy, candidates))

    logger.info("critique: %s  reward=%.4f  filtered=%d  %dms",
                selected.metadata.get("mode"), reward, n_filtered, ms)
    return {
        "selected": selected,
        "reward": reward,
        "messages": [
            f"[critique] mode={selected.metadata.get('mode', '?')}  "
            f"reward={reward:.4f}  filtered={n_filtered}  {ms}ms"
        ],
        "step_events": [{
            "node": "critique",
            "label": "MetaCritic",
            "icon": "🧠",
            "status": "done",
            "duration_ms": ms,
            "summary": f"selected: {selected.metadata.get('mode', '?')}  reward: {reward:.4f}",
            "detail": f"{n_filtered} strategies filtered by policy check",
            "selected_id": selected.id,
            "selected_mode": selected.metadata.get("mode", "?"),
            "reward": round(reward, 4),
            "reward_decomposition": decomp,
            "n_filtered": n_filtered,
        }],
    }


def node_dispatch(state: WorkflowState) -> dict:
    t0 = time.perf_counter()
    selected = state.get("selected")
    if selected is None:
        return {
            "messages": ["[dispatch] no strategy – skipping"],
            "step_events": [{
                "node": "dispatch", "label": "Dispatch", "icon": "📡",
                "status": "skipped", "duration_ms": 0,
                "summary": "no strategy selected", "detail": "",
            }],
        }

    energy = state["energy_state"]
    action = _dispatcher.dispatch(energy, selected)
    ms = int((time.perf_counter() - t0) * 1000)

    logger.info("dispatch: ess=+%.1f/−%.1f kW  market=%.1f kW  %dms",
                action["ess_charge_kw"], action["ess_discharge_kw"],
                action["market_quantity_kw"], ms)
    return {
        "messages": [
            f"[dispatch] ess=+{action['ess_charge_kw']:.1f}/−{action['ess_discharge_kw']:.1f} kW  "
            f"market={action['market_quantity_kw']:.1f} kW@{action['market_price_per_kwh']:.3f}$/kWh  {ms}ms"
        ],
        "step_events": [{
            "node": "dispatch",
            "label": "Dispatch",
            "icon": "📡",
            "status": "done",
            "duration_ms": ms,
            "summary": f"ESS +{action['ess_charge_kw']:.0f}/−{action['ess_discharge_kw']:.0f} kW  "
                       f"Market {action['market_quantity_kw']:.0f} kW",
            "detail": f"PV curtail {action['pv_curtailment_ratio']*100:.0f}%  "
                      f"load shift {action['load_shift_kw']:.1f} kW",
            "ess_charge_kw": action["ess_charge_kw"],
            "ess_discharge_kw": action["ess_discharge_kw"],
            "pv_curtailment_pct": round(action["pv_curtailment_ratio"] * 100, 1),
            "load_shift_kw": action["load_shift_kw"],
            "market_quantity_kw": action["market_quantity_kw"],
            "market_price": action["market_price_per_kwh"],
            "expected_reward": action["expected_reward"],
        }],
    }


# ---------------------------------------------------------------------------
# Build and compile the graph
# ---------------------------------------------------------------------------


def build_workflow():
    graph = StateGraph(WorkflowState)

    graph.add_node("generate", node_generate)
    graph.add_node("optimize", node_optimize)
    graph.add_node("auction", node_auction)
    graph.add_node("critique", node_critique)
    graph.add_node("dispatch", node_dispatch)

    graph.set_entry_point("generate")
    graph.add_edge("generate", "optimize")
    graph.add_edge("optimize", "auction")
    graph.add_edge("auction", "critique")
    graph.add_edge("critique", "dispatch")
    graph.add_edge("dispatch", END)

    return graph.compile()


workflow = build_workflow()


# ---------------------------------------------------------------------------
# Public helper
# ---------------------------------------------------------------------------


async def run_workflow(energy_state: EnergyState) -> WorkflowState:
    """Run the full agentic workflow for one decision cycle."""
    initial: WorkflowState = {
        "energy_state": energy_state,
        "strategies": [],
        "optimized": [],
        "selected": None,
        "reward": 0.0,
        "messages": [],
        "step_events": [],
    }
    result = await workflow.ainvoke(initial)
    return result  # type: ignore[return-value]
