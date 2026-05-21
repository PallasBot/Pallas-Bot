"""AI 任务 HTTP 回调执行（worker / unified 本进程）。"""

from __future__ import annotations

import base64

from fastapi import HTTPException, UploadFile
from nonebot import get_bot

from src.common.config import GroupConfig, TaskManager
from src.common.db import SingProgress
from src.common.shard.coord.ai_task_registry import remove_ai_task


async def run_ai_callback(
    task_id: str,
    *,
    status: str,
    text: str | None = None,
    song_id: str | None = None,
    chunk_index: int | None = None,
    key: int | None = None,
    file: UploadFile | None = None,
) -> dict[str, str]:
    task = await TaskManager.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    bot_id = task.get("bot_id")
    group_id = task.get("group_id")

    try:
        bot = get_bot(bot_id)
    except Exception:
        return {"message": "failed"}

    if group_id and song_id is not None and chunk_index is not None and key is not None:
        config = GroupConfig(group_id)
        sing_progress = SingProgress(
            song_id=str(song_id),
            chunk_index=chunk_index,
            key=key,
        )
        await config.update_sing_progress(sing_progress)

    if status == "failed":
        await TaskManager.remove_task(task_id)
        remove_ai_task(task_id)
        await bot.call_api(
            "send_group_msg",
            **{
                "message": "我习惯了站着不动思考。有时候啊，也会被大家突然戳一戳，看看睡着了没有。",
                "group_id": group_id,
            },
        )
        return {"message": "ok"}

    if status == "success":
        if text:
            await bot.call_api(
                "send_group_msg",
                **{
                    "message": text,
                    "group_id": group_id,
                },
            )
        if file:
            file_content = await file.read()
            base64_file = base64.b64encode(file_content).decode()
            await bot.call_api(
                "send_group_msg",
                **{
                    "message": f"[CQ:record,file=base64://{base64_file}]",
                    "group_id": group_id,
                },
            )

        await TaskManager.remove_task(task_id)
        remove_ai_task(task_id)
        return {"message": "ok"}

    raise HTTPException(status_code=400, detail="Invalid status")
