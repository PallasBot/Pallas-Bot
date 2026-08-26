"""work aux 与 Bot 主进程之间的 AI 任务登记。"""

from __future__ import annotations

import os

import httpx
from fastapi import HTTPException
from pydantic import BaseModel, Field

from pallas.core.foundation.config import TaskManager

_INTERNAL_PATH = "/pallas/api/internal/ai/tasks"


class AiTaskRegistrationRequest(BaseModel):
    task_id: str = Field(min_length=1)
    task_status: dict


def _bot_internal_url(task_id: str) -> str:
    raw_port = (os.environ.get("PORT") or "8088").strip()
    try:
        port = int(raw_port)
    except ValueError:
        port = 8088
    if not 1 <= port <= 65535:
        port = 8088
    return f"http://127.0.0.1:{port}{_INTERNAL_PATH}/{task_id}"


async def register_ai_task_from_aux(
    task_id: str,
    task_status: dict,
    *,
    client_host: str | None = "127.0.0.1",
) -> dict[str, str]:
    if client_host not in {"127.0.0.1", "::1", "localhost"}:
        raise HTTPException(status_code=403, detail="loopback_only")
    await TaskManager.add_task(task_id, task_status)
    return {"message": "ok"}


async def unregister_ai_task_from_aux(task_id: str, *, client_host: str | None = "127.0.0.1") -> dict[str, str]:
    if client_host not in {"127.0.0.1", "::1", "localhost"}:
        raise HTTPException(status_code=403, detail="loopback_only")
    await TaskManager.remove_task(task_id)
    return {"message": "ok"}


async def register_ai_task_in_bot_process(task_id: str, task_status: dict) -> None:
    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.post(
            _bot_internal_url(task_id),
            json={"task_id": task_id, "task_status": task_status},
        )
        response.raise_for_status()


async def unregister_ai_task_in_bot_process(task_id: str) -> None:
    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.delete(_bot_internal_url(task_id))
        response.raise_for_status()
