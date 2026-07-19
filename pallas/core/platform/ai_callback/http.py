"""异步任务 HTTP 回调路由。"""

from __future__ import annotations

from fastapi import File, Form, UploadFile
from nonebot import get_app

from pallas.core.platform.ai_callback.runner import run_ai_callback
from pallas.core.platform.bot_runtime.roles import is_hub_role
from pallas.core.platform.shard.coord.ai_callback_forward import forward_ai_callback_to_worker

_http_registered = False


def register_ai_callback_http() -> None:
    global _http_registered
    if _http_registered:
        return

    app = get_app()

    @app.post("/callback/{task_id}")
    async def ai_callback_route(
        task_id: str,
        status: str = Form(...),
        text: str | None = Form(None),
        agent_trace: str | None = Form(None),
        song_id: str | None = Form(None),
        chunk_index: int | None = Form(None),
        key: int | None = Form(None),
        history_summary: str | None = Form(None),
        history_keep_messages: int | None = Form(None),
        file: UploadFile | None = File(None),  # noqa: B008
    ):
        if is_hub_role():
            return await forward_ai_callback_to_worker(
                task_id,
                status=status,
                text=text,
                agent_trace=agent_trace,
                song_id=song_id,
                chunk_index=chunk_index,
                key=key,
                history_summary=history_summary,
                history_keep_messages=history_keep_messages,
                file=file,
            )
        return await run_ai_callback(
            task_id,
            status=status,
            text=text,
            agent_trace=agent_trace,
            song_id=song_id,
            chunk_index=chunk_index,
            key=key,
            history_summary=history_summary,
            history_keep_messages=history_keep_messages,
            file=file,
        )

    _http_registered = True
