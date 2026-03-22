"""FastAPI application – REST interface for AETOS.

Endpoints:
  GET  /              – dashboard UI
  POST /run           – trigger one optimization cycle
  POST /chat          – natural language interface (deepagents)
  GET  /kpi           – cumulative KPI totals
  GET  /episodes      – recent episode history
  GET  /episodes/{id} – full workflow trace for one episode
  GET  /health        – liveness probe
  GET  /a2a/agents    – registered A2A agent cards
  GET  /mcp/tools     – MCP tool definitions (discovery)
  GET  /mcp/sse       – MCP SSE transport (external MCP clients)
  POST /mcp/messages/ – MCP SSE message endpoint
"""

from __future__ import annotations

from contextlib import asynccontextmanager
import logging
import random
import uuid
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Annotated

import uvicorn
from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db.history import persist_workflow_run
from ..db.models import Episode, KPI
from ..db.session import AsyncSessionLocal, get_session, init_db
from ..config import settings
from ..deep_agent import (
    DeepAgentConfigurationError,
    DeepAgentExecutionError,
    DeepAgentInputError,
    DeepAgentRateLimitError,
    invoke_deep_agent,
)
from ..mcp.server import mcp as _mcp_server
from ..observability import audit_log, metrics, new_request_id, set_request_context, timed
from ..runtime import runtime
from ..security import authorize_request
from ..state import Constraints, EnergyState
from ..workflow import get_agent_cards, run_workflow

logger = logging.getLogger(__name__)

STATIC_DIR = Path(__file__).parent / "static"


@asynccontextmanager
async def lifespan(_: FastAPI):
    try:
        await init_db()
        logger.info("AETOS API started (PostgreSQL connected)")
    except Exception as e:
        logger.warning("DB unavailable – running in memory-only mode: %s", e)
    yield


app = FastAPI(
    title="AETOS",
    description="Autonomous Agentic Energy Trading & Optimization System",
    version="0.1.0",
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in settings.cors_allow_origins.split(",") if o.strip()] or ["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
app.mount("/mcp", _mcp_server.sse_app())  # MCP SSE transport for external clients

# In-memory fallback store (when PostgreSQL is unavailable)
_mem_episodes: deque[dict] = deque(maxlen=200)


# ---------------------------------------------------------------------------
# Request / Response schemas
# ---------------------------------------------------------------------------


class RunRequest(BaseModel):
    goal: str = "optimize"
    state: EnergyState | None = None  # inject custom state for testing


class RunResponse(BaseModel):
    status: str
    timestamp: str
    energy_state: dict
    step_events: list[dict]
    all_strategies: list[dict]   # all optimized candidates (for strategy chart)
    selected_strategy: dict | None
    reward: float
    reward_decomposition: dict
    messages: list[str]


class EpisodeItem(BaseModel):
    id: str
    timestamp: str
    source: str
    reward: float
    mode: str
    cost_saving: float
    ess_profit: float
    roi: float


class EpisodeDetail(BaseModel):
    id: str
    timestamp: str
    source: str
    energy_state: dict
    action: dict
    reward: float
    reward_decomposition: dict
    messages: list[str]
    step_events: list[dict]
    cost_saving: float
    ess_profit: float
    roi: float


class KPIResponse(BaseModel):
    cost_saving: float
    ess_profit: float
    roi: float
    avg_reward: float
    n_episodes: int


class ChatRequest(BaseModel):
    message: str


class ChatResponse(BaseModel):
    reply: str


# ---------------------------------------------------------------------------
# Middleware / Helpers
# ---------------------------------------------------------------------------


@app.middleware("http")
async def ops_middleware(request: Request, call_next):
    request_id = request.headers.get("x-request-id") or new_request_id()
    path = request.url.path

    try:
        auth = authorize_request(request)
        set_request_context(request_id=request_id, actor=auth.actor, scope=auth.scope)
    except HTTPException as exc:
        set_request_context(request_id=request_id, actor="anonymous", scope="denied")
        metrics.incr("http.denied")
        audit_log(
            "http.denied",
            path=path,
            method=request.method,
            status_code=exc.status_code,
        )
        return JSONResponse(
            status_code=exc.status_code,
            content={"detail": exc.detail},
            headers={"x-request-id": request_id},
        )

    try:
        with timed("http.request", audit_event="http.request", path=path, method=request.method):
            response = await call_next(request)
    except Exception:
        metrics.incr("http.error")
        audit_log("http.error", path=path, method=request.method)
        raise

    metrics.incr(f"http.status.{response.status_code}")
    response.headers["x-request-id"] = request_id
    return response


def _mock_state() -> EnergyState:
    h = datetime.now().hour
    price = [
        round(max(0.01, 0.04 + 0.06 * (9 <= (h + i) % 24 <= 18) + random.gauss(0, 0.005)), 4)
        for i in range(24)
    ]
    load = [
        round(max(0, 20 + 15 * (8 <= (h + i) % 24 <= 21) + random.gauss(0, 2)), 2)
        for i in range(24)
    ]
    gen = [
        round(max(0, 30 * (1 - abs((h + i) % 24 - 13) / 8) + random.gauss(0, 1)), 2)
        for i in range(24)
    ]
    return EnergyState(
        price=price,
        load=load,
        generation=gen,
        ess_soc=round(random.uniform(0.3, 0.7), 2),
        constraints=Constraints(export_limit=50.0, soc_min=0.1, soc_max=0.9),
        timestamp=datetime.now(timezone.utc).isoformat(),
    )


def _strategy_dict(s) -> dict | None:
    if s is None:
        return None
    return {
        "id": s.id,
        "mode": s.metadata.get("mode", "?"),
        "bid": round(s.bid, 4),
        "ess_charge": round(s.ess.charge_rate, 2),
        "ess_discharge": round(s.ess.discharge_rate, 2),
        "pv_curtailment": round(s.pv.curtailment_ratio, 3),
        "load_shift": round(s.load.shift_amount, 2),
        "market_qty": round(s.market.quantity, 2),
        "market_price": round(s.market.price, 4),
    }


async def _persist(energy: EnergyState, result: dict, decomp: dict) -> None:
    """Write episode + KPI to DB, silently skip if DB is unavailable."""
    selected = result.get("selected")
    reward = result.get("reward", 0.0)

    ep_id = await persist_workflow_run(energy, result, source="api")
    _mem_episodes.appendleft({
        "id": ep_id or str(uuid.uuid4()),
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "reward": reward,
        "source": "api",
        "mode": selected.metadata.get("mode", "?") if selected else "none",
        "cost_saving": decomp.get("cost_saving", reward * 0.3),
        "ess_profit": decomp.get("ess_profit", reward * 0.3),
        "roi": decomp.get("solar_roi", reward * 0.2),
    })


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@app.get("/", include_in_schema=False)
async def dashboard() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/health")
async def health() -> dict:
    return {"status": "ok", "timestamp": datetime.now(timezone.utc).isoformat()}


@app.get("/a2a/agents")
async def a2a_agents() -> list[dict]:
    return get_agent_cards()


@app.get("/a2a/policy")
async def a2a_policy() -> dict:
    return runtime.a2a_policy()


@app.get("/metrics")
async def get_metrics() -> dict:
    return metrics.snapshot()


@app.get("/mcp/tools")
async def mcp_tools() -> list[dict]:
    """등록된 MCP 도구 목록과 스키마를 반환합니다 (discovery)."""
    tools = await _mcp_server.list_tools()
    return [
        {
            "name": t.name,
            "description": t.description,
            "inputSchema": t.inputSchema,
        }
        for t in tools
    ]


@app.post("/chat", response_model=ChatResponse)
async def chat(body: ChatRequest) -> ChatResponse:
    """deepagents deep agent를 통해 자연어로 에너지 최적화를 요청합니다."""
    try:
        reply = await invoke_deep_agent(body.message)
    except DeepAgentInputError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except DeepAgentConfigurationError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except DeepAgentRateLimitError as exc:
        raise HTTPException(status_code=429, detail=str(exc)) from exc
    except DeepAgentExecutionError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return ChatResponse(reply=reply)


@app.post("/run", response_model=RunResponse)
async def run(body: RunRequest) -> RunResponse:
    """Trigger one optimization cycle and return full step trace."""
    energy = body.state or _mock_state()
    result = await run_workflow(energy)

    selected = result.get("selected")
    reward = result.get("reward", 0.0)
    decomp = selected.metadata.get("reward_decomposition", {}) if selected else {}

    # Collect all optimized strategies from step_events for the strategy chart
    all_strategies: list[dict] = []
    for ev in result.get("step_events", []):
        if ev["node"] == "optimize" and "strategies" in ev:
            all_strategies = ev["strategies"]
            break

    await _persist(energy, result, decomp)

    return RunResponse(
        status="ok",
        timestamp=datetime.now(timezone.utc).isoformat(),
        energy_state=energy.model_dump(),
        step_events=result.get("step_events", []),
        all_strategies=all_strategies,
        selected_strategy=_strategy_dict(selected),
        reward=reward,
        reward_decomposition=decomp,
        messages=result.get("messages", []),
    )


@app.get("/episodes")
async def get_episodes(limit: int = Query(default=50, le=200)) -> list[EpisodeItem]:
    """Return recent episode history (DB first, in-memory fallback)."""
    try:
        async with AsyncSessionLocal() as session:
            rows = (
                await session.execute(
                    select(Episode, KPI)
                    .outerjoin(KPI, Episode.id == KPI.episode_id)
                    .order_by(desc(Episode.timestamp))
                    .limit(limit)
                )
            ).all()
            if rows:
                items = []
                for ep, kpi in rows:
                    items.append(EpisodeItem(
                        id=ep.id,
                        timestamp=ep.timestamp.isoformat(),
                        source=getattr(ep, "source", None) or "api",
                        reward=ep.reward,
                        mode=ep.action.get("metadata", {}).get("mode", "?") if ep.action else "?",
                        cost_saving=kpi.cost_saving if kpi else ep.reward * 0.3,
                        ess_profit=kpi.ess_profit if kpi else ep.reward * 0.3,
                        roi=kpi.roi if kpi else ep.reward * 0.2,
                    ))
                return items
    except Exception:
        pass

    # in-memory fallback
    return [
        EpisodeItem(
            id=ep["id"],
            timestamp=ep["timestamp"],
            source=ep.get("source", "api"),
            reward=ep["reward"],
            mode=ep["mode"],
            cost_saving=ep["cost_saving"],
            ess_profit=ep["ess_profit"],
            roi=ep["roi"],
        )
        for ep in list(_mem_episodes)[:limit]
    ]


@app.get("/episodes/{episode_id}", response_model=EpisodeDetail)
async def get_episode(episode_id: str) -> EpisodeDetail:
    """Return one episode including full workflow trace (for audit / replay)."""
    try:
        async with AsyncSessionLocal() as session:
            row = (
                await session.execute(
                    select(Episode, KPI)
                    .outerjoin(KPI, Episode.id == KPI.episode_id)
                    .where(Episode.id == episode_id)
                )
            ).one_or_none()
            if not row:
                raise HTTPException(status_code=404, detail="episode not found")
            ep, kpi = row
            rd = ep.reward_decomposition if isinstance(ep.reward_decomposition, dict) else {}
            return EpisodeDetail(
                id=ep.id,
                timestamp=ep.timestamp.isoformat(),
                source=getattr(ep, "source", None) or "api",
                energy_state=ep.state,
                action=ep.action,
                reward=ep.reward,
                reward_decomposition=rd,
                messages=list(ep.messages or []),
                step_events=list(ep.step_events or []),
                cost_saving=kpi.cost_saving if kpi else float(rd.get("cost_saving", ep.reward * 0.3)),
                ess_profit=kpi.ess_profit if kpi else float(rd.get("ess_profit", ep.reward * 0.3)),
                roi=kpi.roi if kpi else float(rd.get("solar_roi", ep.reward * 0.2)),
            )
    except HTTPException:
        raise
    except Exception:
        pass

    for ep in _mem_episodes:
        if ep["id"] == episode_id:
            return EpisodeDetail(
                id=ep["id"],
                timestamp=ep["timestamp"],
                source=ep.get("source", "api"),
                energy_state={},
                action={},
                reward=ep["reward"],
                reward_decomposition={},
                messages=[],
                step_events=[],
                cost_saving=ep["cost_saving"],
                ess_profit=ep["ess_profit"],
                roi=ep["roi"],
            )
    raise HTTPException(status_code=404, detail="episode not found")


@app.get("/kpi", response_model=KPIResponse)
async def get_kpi() -> KPIResponse:
    """Return cumulative KPI totals."""
    try:
        async with AsyncSessionLocal() as session:
            kpi_row = (
                await session.execute(
                    select(
                        func.coalesce(func.sum(KPI.cost_saving), 0.0),
                        func.coalesce(func.sum(KPI.ess_profit), 0.0),
                        func.coalesce(func.sum(KPI.roi), 0.0),
                    )
                )
            ).one()
            ep_row = (
                await session.execute(
                    select(
                        func.coalesce(func.avg(Episode.reward), 0.0),
                        func.count(Episode.id),
                    )
                )
            ).one()
            return KPIResponse(
                cost_saving=kpi_row[0],
                ess_profit=kpi_row[1],
                roi=kpi_row[2],
                avg_reward=ep_row[0],
                n_episodes=int(ep_row[1]),
            )
    except Exception:
        pass

    # in-memory fallback
    eps = list(_mem_episodes)
    if not eps:
        return KPIResponse(cost_saving=0, ess_profit=0, roi=0, avg_reward=0, n_episodes=0)
    return KPIResponse(
        cost_saving=sum(e["cost_saving"] for e in eps),
        ess_profit=sum(e["ess_profit"] for e in eps),
        roi=sum(e["roi"] for e in eps),
        avg_reward=sum(e["reward"] for e in eps) / len(eps),
        n_episodes=len(eps),
    )


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    uvicorn.run("aetos.api.app:app", host="0.0.0.0", port=8000, reload=False)
