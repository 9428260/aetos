"""Minimal Agent-to-Agent protocol models used by AETOS."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, Field


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class A2AArtifact(BaseModel):
    name: str
    content_type: str = "application/json"
    data: dict[str, Any] = Field(default_factory=dict)


class A2AMessage(BaseModel):
    message_id: str = Field(default_factory=lambda: str(uuid4()))
    role: Literal["requester", "agent", "system"] = "requester"
    parts: list[dict[str, Any]] = Field(default_factory=list)
    timestamp: str = Field(default_factory=utc_now)


class A2ATask(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    agent: str
    skill: str
    session_id: str = Field(default_factory=lambda: str(uuid4()))
    message: A2AMessage
    input: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)


class A2ATaskResult(BaseModel):
    task_id: str
    agent: str
    status: Literal["completed", "failed"] = "completed"
    message: A2AMessage
    artifacts: list[A2AArtifact] = Field(default_factory=list)
    metrics: dict[str, Any] = Field(default_factory=dict)


class A2AAgentCard(BaseModel):
    name: str
    description: str
    skills: list[str]
    version: str = "1.0"
