from __future__ import annotations

import time
from typing import Any

from pydantic import BaseModel, Field


class Artifact(BaseModel):
    artifact_id: str = ""
    kind: str = "text"
    content: str = ""
    created_at: int = Field(default_factory=lambda: int(time.time()))


class TaskRecord(BaseModel):
    task_id: str
    name: str
    status: str = "pending"
    payload: dict[str, Any] = Field(default_factory=dict)
    group_id: int | None = None
    user_id: int | None = None
    run_at: int | None = None
    interval_sec: int = 0
    created_at: int = Field(default_factory=lambda: int(time.time()))
    updated_at: int = Field(default_factory=lambda: int(time.time()))
    artifacts: list[Artifact] = Field(default_factory=list)


class SubAgentRun(BaseModel):
    run_id: str
    task_id: str
    status: str = "planned"
    allowed_tools: list[str] = Field(default_factory=list)
    budget: int = 3
    deadline: int | None = None
    planned_steps: list[str] = Field(default_factory=list)
    artifacts: list[Artifact] = Field(default_factory=list)
