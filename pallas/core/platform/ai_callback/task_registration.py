"""work aux 与 Bot 主进程之间的 AI 任务登记。

POST/DELETE 强制内部 header（由共享根密钥按用途标签派生），loopback 仅纵深防御；
客户端 trust_env=False 且不跟随重定向。
"""

from __future__ import annotations

import os
import re

import httpx
from fastapi import HTTPException
from pydantic import BaseModel, Field

from pallas.core.foundation.config import TaskManager
from pallas.core.platform.ai_callback.internal_auth import (
    INTERNAL_TOKEN_HEADER,
    PURPOSE_AI_TASK_REGISTRATION,
    internal_auth_headers,
    verify_internal_token,
)

_INTERNAL_PATH = "/pallas/api/internal/ai/tasks"
_TASK_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,128}$")


def valid_task_id(task_id: str) -> bool:
    return bool(_TASK_ID_RE.match(str(task_id or "")))


class AiTaskRegistrationRequest(BaseModel):
    task_id: str = Field(min_length=1, max_length=128)
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


def _require_internal_token(internal_token: str | None) -> None:
    if not verify_internal_token(PURPOSE_AI_TASK_REGISTRATION, internal_token):
        raise HTTPException(status_code=403, detail="internal_token_required")


async def register_ai_task_from_aux(
    task_id: str,
    task_status: dict,
    *,
    client_host: str | None = "127.0.0.1",
    internal_token: str | None = None,
) -> dict[str, str]:
    _ = client_host
    _require_internal_token(internal_token)
    if not valid_task_id(task_id):
        raise HTTPException(status_code=400, detail="invalid_task_id")
    from pallas.core.platform.ai_callback.task_types import is_retired_chat_task_type

    if isinstance(task_status, dict) and is_retired_chat_task_type(task_status.get("task_type")):
        raise HTTPException(status_code=410, detail="legacy_agent_retired")
    from pallas.core.platform.shard.coord.ai_task_registry import AiTaskRedisError

    try:
        status = await TaskManager.add_task(task_id, task_status)
    except AiTaskRedisError as exc:
        raise HTTPException(status_code=503, detail="task_register_retry") from exc
    if status == "invalid":
        raise HTTPException(status_code=400, detail="invalid_task_status")
    if status == "conflict":
        raise HTTPException(status_code=409, detail="task_conflict")
    return {"message": "ok"}


async def unregister_ai_task_from_aux(
    task_id: str,
    *,
    client_host: str | None = "127.0.0.1",
    internal_token: str | None = None,
) -> dict[str, str]:
    _ = client_host
    _require_internal_token(internal_token)
    if not valid_task_id(task_id):
        raise HTTPException(status_code=400, detail="invalid_task_id")
    from pallas.core.platform.shard.coord.ai_task_registry import AiTaskRedisError

    try:
        await TaskManager.remove_task(task_id)
    except AiTaskRedisError as exc:
        raise HTTPException(status_code=503, detail="task_cancel_retry") from exc
    return {"message": "ok"}


def _internal_client() -> httpx.AsyncClient:
    return httpx.AsyncClient(timeout=10.0, trust_env=False, follow_redirects=False)


async def register_ai_task_in_bot_process(task_id: str, task_status: dict) -> None:
    async with _internal_client() as client:
        response = await client.post(
            _bot_internal_url(task_id),
            json={"task_id": task_id, "task_status": task_status},
            headers=internal_auth_headers(PURPOSE_AI_TASK_REGISTRATION),
        )
        response.raise_for_status()


async def unregister_ai_task_in_bot_process(task_id: str) -> None:
    async with _internal_client() as client:
        response = await client.delete(
            _bot_internal_url(task_id),
            headers=internal_auth_headers(PURPOSE_AI_TASK_REGISTRATION),
        )
        response.raise_for_status()


__all__ = [
    "INTERNAL_TOKEN_HEADER",
    "AiTaskRegistrationRequest",
    "register_ai_task_from_aux",
    "register_ai_task_in_bot_process",
    "unregister_ai_task_from_aux",
    "unregister_ai_task_in_bot_process",
    "valid_task_id",
]
