"""分片 hub：将 Pallas-Bot-AI 的 /callback 转发到登记 worker。"""

from __future__ import annotations

from typing import Any

import httpx
from fastapi import HTTPException, UploadFile
from nonebot import logger

from pallas.core.platform.shard.coord.ai_task_registry import resolve_worker_port_for_task


async def forward_ai_callback_to_worker(
    task_id: str,
    *,
    status: str,
    text: str | None = None,
    agent_trace: str | None = None,
    song_id: str | None = None,
    chunk_index: int | None = None,
    key: int | None = None,
    history_summary: str | None = None,
    history_keep_messages: int | None = None,
    file: UploadFile | None = None,
) -> dict[str, Any]:
    port = resolve_worker_port_for_task(task_id)
    if port is None:
        raise HTTPException(status_code=404, detail="Task not found")

    data: dict[str, str] = {"status": status}
    if text is not None:
        data["text"] = text
    if agent_trace is not None:
        data["agent_trace"] = agent_trace
    if song_id is not None:
        data["song_id"] = str(song_id)
    if chunk_index is not None:
        data["chunk_index"] = str(chunk_index)
    if key is not None:
        data["key"] = str(key)
    if history_summary is not None:
        data["history_summary"] = history_summary
    if history_keep_messages is not None:
        data["history_keep_messages"] = str(int(history_keep_messages))

    files = None
    if file is not None:
        body = await file.read()
        files = {"file": (file.filename or "audio", body, file.content_type or "application/octet-stream")}

    url = f"http://127.0.0.1:{port}/callback/{task_id}"
    timeout = httpx.Timeout(120.0, connect=10.0)
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(url, data=data, files=files)
    except httpx.HTTPError as err:
        logger.warning("ai_callback forward task_id={} port={}: {}", task_id, port, err)
        raise HTTPException(status_code=502, detail="分片节点回调不可达") from err

    if resp.status_code == 404:
        raise HTTPException(status_code=404, detail="分片节点上未找到任务")
    if resp.status_code >= 400:
        logger.warning(
            "ai_callback forward task_id={} port={} status={} body={}",
            task_id,
            port,
            resp.status_code,
            resp.text[:200],
        )
        raise HTTPException(status_code=502, detail="分片节点回调失败")
    try:
        return resp.json()
    except Exception:
        return {"message": "ok"}
