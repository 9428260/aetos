"""deepagents orchestration layer for AETOS."""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from collections import deque
from collections.abc import Sequence
from typing import Any

from deepagents import SubAgent, create_deep_agent
from langchain_core.messages import HumanMessage
from langchain_core.tools import tool
from langchain_openai import AzureChatOpenAI

from .config import settings
from .mcp.server import mcp as _mcp
from .observability import audit_log, metrics, timed
from .runtime import runtime
from .state import EnergyState, Strategy

logger = logging.getLogger(__name__)
_deep_agent_semaphore = asyncio.Semaphore(max(1, settings.deep_agent_max_concurrency))
_deep_agent_rate_lock = asyncio.Lock()
_deep_agent_requests: deque[float] = deque()


class DeepAgentError(RuntimeError):
    """Base error for deep agent integration."""


class DeepAgentInputError(DeepAgentError):
    """Raised when the chat request cannot be validated."""


class DeepAgentConfigurationError(DeepAgentError):
    """Raised when required LLM configuration is missing."""


class DeepAgentExecutionError(DeepAgentError):
    """Raised when the deep agent execution fails."""


class DeepAgentRateLimitError(DeepAgentExecutionError):
    """Raised when the deep agent rate limit is exceeded."""


def validate_chat_message(message: str) -> str:
    cleaned = message.strip()
    if not cleaned:
        raise DeepAgentInputError("message must not be empty")
    if len(cleaned) > 8000:
        raise DeepAgentInputError("message is too long")
    return cleaned


def extract_energy_state_payload(message: str) -> dict[str, Any] | None:
    code_block = re.search(r"```json\s*(\{.*?\})\s*```", message, flags=re.DOTALL)
    candidate = code_block.group(1) if code_block else None

    if candidate is None:
        stripped = message.strip()
        if stripped.startswith("{") and stripped.endswith("}"):
            candidate = stripped

    if candidate is None:
        return None

    try:
        payload = json.loads(candidate)
    except json.JSONDecodeError as exc:
        raise DeepAgentInputError(f"invalid EnergyState JSON: {exc.msg}") from exc

    try:
        energy = EnergyState.model_validate(payload)
    except Exception as exc:
        raise DeepAgentInputError(f"invalid EnergyState payload: {exc}") from exc
    return energy.model_dump()


def _normalize_text_content(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict) and item.get("type") == "text":
                parts.append(str(item.get("text", "")))
        return "\n".join(part for part in parts if part).strip()
    return str(content).strip()


def _validate_state_payload(state: dict[str, Any]) -> EnergyState:
    try:
        return EnergyState.model_validate(state)
    except Exception as exc:
        raise DeepAgentInputError(f"invalid state payload: {exc}") from exc


def _validate_strategy_payload(strategy: dict[str, Any]) -> Strategy:
    try:
        return Strategy.model_validate(strategy)
    except Exception as exc:
        raise DeepAgentInputError(f"invalid strategy payload: {exc}") from exc


async def _call_mcp(tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    """FastMCP in-process 호출 — 실제 MCP 프로토콜 dispatch를 경유합니다."""
    results = await _mcp.call_tool(tool_name, arguments)
    if not results:
        return {}
    try:
        return json.loads(results[0].text)
    except (json.JSONDecodeError, AttributeError):
        return {"result": str(results[0])}


@tool
async def mcp_forecast(horizon: int = 24) -> dict:
    """Forecast electricity price, load, and solar generation via MCP."""
    return await _call_mcp("forecast", {"horizon": horizon})


@tool
async def mcp_optimize(state: dict[str, Any]) -> dict:
    """Run the full AETOS optimization workflow via MCP (generate→optimize→auction→critique→dispatch)."""
    _validate_state_payload(state)
    return await _call_mcp("optimize", {"state": state})


@tool
async def mcp_policy_check(strategy: dict[str, Any], state: dict[str, Any]) -> dict:
    """Validate a strategy against grid and system constraints via MCP."""
    _validate_strategy_payload(strategy)
    _validate_state_payload(state)
    return await _call_mcp("policy_check", {"strategy": strategy, "state": state})


@tool
async def mcp_dispatch(
    strategy: dict[str, Any],
    state: dict[str, Any] | None = None,
    dry_run: bool = True,
) -> dict:
    """Dispatch a strategy to physical assets via MCP."""
    _validate_strategy_payload(strategy)
    if state is not None:
        _validate_state_payload(state)
    args: dict[str, Any] = {"strategy": strategy, "dry_run": dry_run}
    if state is not None:
        args["state"] = state
    return await _call_mcp("dispatch", args)


@tool
async def mcp_kpi() -> dict:
    """Retrieve the latest KPI snapshot via MCP."""
    return await _call_mcp("kpi", {})


@tool
def a2a_generate_strategies(energy_state: dict[str, Any]) -> dict:
    """Generate candidate strategies through the A2A broker."""
    energy = _validate_state_payload(energy_state)
    session = runtime.new_session()
    result = session.broker.send_task(
        agent="strategy-generator",
        skill="generate_strategies",
        input={"energy_state": energy.model_dump()},
    )
    return result.artifacts[0].data


@tool
def a2a_optimize_strategies(
    energy_state: dict[str, Any],
    strategies: list[dict[str, Any]],
) -> dict:
    """Optimize candidate strategies through the A2A broker."""
    energy = _validate_state_payload(energy_state)
    validated = [_validate_strategy_payload(s).model_dump() for s in strategies]
    session = runtime.new_session()
    result = session.broker.send_task(
        agent="optimizer",
        skill="optimize_strategies",
        input={"energy_state": energy.model_dump(), "strategies": validated},
    )
    return result.artifacts[0].data


@tool
def a2a_select_strategy(
    energy_state: dict[str, Any],
    candidates: list[dict[str, Any]],
) -> dict:
    """Select the best strategy through the A2A broker."""
    energy = _validate_state_payload(energy_state)
    validated = [_validate_strategy_payload(s).model_dump() for s in candidates]
    session = runtime.new_session()
    result = session.broker.send_task(
        agent="meta-critic",
        skill="select_strategy",
        input={"energy_state": energy.model_dump(), "candidates": validated},
    )
    return result.artifacts[0].data


@tool
def a2a_dispatch_strategy(energy_state: dict[str, Any], strategy: dict[str, Any]) -> dict:
    """Dispatch the selected strategy through the A2A broker."""
    energy = _validate_state_payload(energy_state)
    validated = _validate_strategy_payload(strategy)
    session = runtime.new_session()
    result = session.broker.send_task(
        agent="dispatcher",
        skill="dispatch_strategy",
        input={
            "energy_state": energy.model_dump(),
            "strategy": validated.model_dump(),
            "dry_run": True,
        },
    )
    return result.artifacts[0].data


def get_deep_agent_tools() -> Sequence[Any]:
    return [
        mcp_forecast,
        mcp_optimize,
        mcp_policy_check,
        mcp_dispatch,
        mcp_kpi,
    ]


def get_deep_agent_subagents() -> list[SubAgent]:
    return [
        {
            "name": "strategy-specialist",
            "description": "Generate and refine candidate strategies through A2A agents.",
            "system_prompt": (
                "Handle strategy generation requests.\n"
                "Use a2a_generate_strategies to create candidates.\n"
                "Use a2a_optimize_strategies when refinement is required.\n"
                "Return concise summaries with counts, dominant modes, and notable bid changes."
            ),
            "tools": [a2a_generate_strategies, a2a_optimize_strategies],
        },
        {
            "name": "selection-specialist",
            "description": "Validate or choose the best strategy using A2A and MCP checks.",
            "system_prompt": (
                "Handle final strategy selection and dispatch preparation.\n"
                "Use a2a_select_strategy to pick a candidate.\n"
                "Use mcp_policy_check when constraint validation is required.\n"
                "Use a2a_dispatch_strategy only when explicitly asked to dispatch."
            ),
            "tools": [a2a_select_strategy, a2a_dispatch_strategy, mcp_policy_check],
        },
    ]


def build_azure_model() -> AzureChatOpenAI:
    required = {
        "AZURE_OPENAI_ENDPOINT": settings.azure_openai_endpoint,
        "AZURE_OPENAI_API_KEY": settings.azure_openai_api_key,
        "AZURE_OPENAI_DEPLOYMENT": settings.azure_openai_deployment,
        "AZURE_OPENAI_API_VERSION": settings.azure_openai_api_version,
    }
    missing = [name for name, value in required.items() if not value]
    if missing:
        raise DeepAgentConfigurationError(
            "missing Azure OpenAI settings: " + ", ".join(missing)
        )

    return AzureChatOpenAI(
        azure_endpoint=settings.azure_openai_endpoint,
        api_key=settings.azure_openai_api_key,
        azure_deployment=settings.azure_openai_deployment,
        api_version=settings.azure_openai_api_version,
    )


def build_deep_agent():
    model = build_azure_model()
    return create_deep_agent(
        model=model,
        tools=get_deep_agent_tools(),
        subagents=get_deep_agent_subagents(),
        system_prompt=(
            "You are the AETOS orchestration agent.\n"
            "Use MCP tools for forecasting, optimization, policy checks, dispatch, and KPI lookup.\n"
            "Delegate specialized candidate generation or selection work to the A2A subagents when the task is multi-step.\n"
            "If the user provides EnergyState JSON, preserve it exactly.\n"
            "Never invent dispatch results or KPI values; call tools.\n"
            "If required data is missing, say so explicitly instead of guessing."
        ),
        name="aetos-deep-agent",
    )


_deep_agent = None


def get_deep_agent():
    global _deep_agent
    if _deep_agent is None:
        _deep_agent = build_deep_agent()
    return _deep_agent


async def _enforce_rate_limit() -> None:
    limit = max(1, settings.deep_agent_requests_per_minute)
    now = time.monotonic()
    async with _deep_agent_rate_lock:
        while _deep_agent_requests and now - _deep_agent_requests[0] >= 60:
            _deep_agent_requests.popleft()
        if len(_deep_agent_requests) >= limit:
            metrics.incr("deep_agent.rate_limited")
            raise DeepAgentRateLimitError("deep agent rate limit exceeded")
        _deep_agent_requests.append(now)


def _fallback_reply(payload: dict[str, Any] | None, reason: str) -> str:
    if settings.deep_agent_fallback_mode.strip().lower() != "workflow":
        raise DeepAgentExecutionError(reason)
    if payload is None:
        raise DeepAgentExecutionError(reason)

    energy = EnergyState.model_validate(payload)
    result = runtime.optimize_via_a2a(energy)
    mode = result.get("metadata", {}).get("mode", "unknown")
    reward = float(result.get("reward", 0.0))
    metrics.incr("deep_agent.fallback")
    audit_log("deep_agent.fallback", reason=reason, mode=mode)
    return (
        "deepagents fallback response\n"
        f"selected_strategy={mode}\n"
        f"reward={reward:.4f}\n"
        "source=deterministic_workflow"
    )


async def invoke_deep_agent(message: str) -> str:
    cleaned = validate_chat_message(message)
    payload = extract_energy_state_payload(cleaned)

    prompt = cleaned
    if payload is not None:
        prompt = (
            "User request with validated EnergyState JSON:\n"
            f"{json.dumps(payload, ensure_ascii=True)}"
        )

    await _enforce_rate_limit()
    try:
        async with _deep_agent_semaphore:
            with timed("deep_agent.invoke", audit_event="deep_agent.invoke"):
                result = await asyncio.wait_for(
                    get_deep_agent().ainvoke({"messages": [HumanMessage(content=prompt)]}),
                    timeout=settings.deep_agent_timeout_seconds,
                )
    except DeepAgentError:
        raise
    except asyncio.TimeoutError:
        return _fallback_reply(payload, "deep agent timed out")
    except Exception as exc:
        logger.exception("deep agent execution failed")
        return _fallback_reply(payload, f"deep agent failed: {exc}")

    messages = result.get("messages", [])
    if not messages:
        return _fallback_reply(payload, "deep agent returned no messages")

    reply = _normalize_text_content(messages[-1].content)
    if not reply:
        return _fallback_reply(payload, "deep agent returned an empty response")
    metrics.incr("deep_agent.success")
    return reply
