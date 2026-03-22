"""Lightweight observability helpers for request context, metrics, and audit logs."""

from __future__ import annotations

import contextvars
import json
import logging
import threading
import time
from collections import defaultdict
from contextlib import contextmanager
from typing import Any
from uuid import uuid4

logger = logging.getLogger("aetos.audit")

request_id_var: contextvars.ContextVar[str] = contextvars.ContextVar("request_id", default="")
actor_var: contextvars.ContextVar[str] = contextvars.ContextVar("actor", default="anonymous")
scope_var: contextvars.ContextVar[str] = contextvars.ContextVar("scope", default="public")


class MetricsRegistry:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._counters: dict[str, int] = defaultdict(int)
        self._durations: dict[str, dict[str, float]] = defaultdict(
            lambda: {"count": 0, "total_ms": 0.0, "max_ms": 0.0}
        )

    def incr(self, key: str, value: int = 1) -> None:
        with self._lock:
            self._counters[key] += value

    def observe_ms(self, key: str, duration_ms: float) -> None:
        with self._lock:
            row = self._durations[key]
            row["count"] += 1
            row["total_ms"] += duration_ms
            row["max_ms"] = max(row["max_ms"], duration_ms)

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            durations = {}
            for key, row in self._durations.items():
                count = int(row["count"])
                total_ms = float(row["total_ms"])
                durations[key] = {
                    "count": count,
                    "total_ms": round(total_ms, 3),
                    "avg_ms": round(total_ms / count, 3) if count else 0.0,
                    "max_ms": round(float(row["max_ms"]), 3),
                }
            return {
                "counters": dict(self._counters),
                "durations": durations,
            }


metrics = MetricsRegistry()


def new_request_id() -> str:
    return str(uuid4())


def set_request_context(*, request_id: str, actor: str, scope: str) -> None:
    request_id_var.set(request_id)
    actor_var.set(actor)
    scope_var.set(scope)


def current_context() -> dict[str, str]:
    return {
        "request_id": request_id_var.get() or "",
        "actor": actor_var.get() or "anonymous",
        "scope": scope_var.get() or "public",
    }


def audit_log(event: str, **fields: Any) -> None:
    payload = {"event": event, **current_context(), **fields}
    logger.info(json.dumps(payload, ensure_ascii=True, sort_keys=True))


@contextmanager
def timed(metric_name: str, *, audit_event: str | None = None, **audit_fields: Any):
    start = time.perf_counter()
    try:
        yield
    finally:
        duration_ms = (time.perf_counter() - start) * 1000
        metrics.observe_ms(metric_name, duration_ms)
        if audit_event:
            audit_log(audit_event, duration_ms=round(duration_ms, 3), **audit_fields)
