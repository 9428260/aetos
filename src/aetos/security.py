"""API authentication and authorization helpers."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from fastapi import HTTPException, Request, status

from .config import settings


@dataclass(frozen=True)
class AuthContext:
    actor: str
    scope: str
    api_key: str


def _parse_keys(raw: str) -> set[str]:
    return {item.strip() for item in raw.split(",") if item.strip()}


def auth_enabled() -> bool:
    return any(
        (
            _parse_keys(settings.api_read_keys),
            _parse_keys(settings.api_write_keys),
            _parse_keys(settings.api_admin_keys),
        )
    )


def classify_scope(path: str, method: str) -> str:
    if path.startswith("/health") or path.startswith("/static") or path == "/":
        return "public"
    if path.startswith("/mcp"):
        return "admin"
    if method.upper() == "GET":
        return "read"
    return "write"


def _scope_keys(scope: str) -> set[str]:
    read = _parse_keys(settings.api_read_keys)
    write = _parse_keys(settings.api_write_keys)
    admin = _parse_keys(settings.api_admin_keys)

    if scope == "read":
        return read | write | admin
    if scope == "write":
        return write | admin
    if scope == "admin":
        return admin
    return set()


def authorize_request(request: Request) -> AuthContext:
    scope = classify_scope(request.url.path, request.method)
    if scope == "public" or not auth_enabled():
        actor = request.headers.get("x-actor-id", "anonymous")
        return AuthContext(actor=actor, scope=scope, api_key="")

    api_key = request.headers.get("x-api-key", "").strip()
    allowed = _scope_keys(scope)
    if not api_key or api_key not in allowed:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"missing or invalid API key for scope '{scope}'",
        )

    actor = request.headers.get("x-actor-id", f"api-key:{scope}")
    return AuthContext(actor=actor, scope=scope, api_key=api_key)


def require_admin_token(token: str | None, *, source: str) -> None:
    if not _parse_keys(settings.api_admin_keys):
        return
    if not token or token not in _parse_keys(settings.api_admin_keys):
        raise PermissionError(f"{source} requires an admin token")
