"""AI 任务 HTTP 回调执行。"""

from __future__ import annotations

import base64

from fastapi import HTTPException, UploadFile
from nonebot import get_bot, logger
from nonebot.adapters.onebot.v11.exception import NetworkError
from nonebot.exception import ActionFailed

from src.foundation.config import GroupConfig, TaskManager
from src.foundation.db import SingProgress
from src.platform.shard.coord.ai_task_registry import get_ai_task_record, remove_ai_task

_CALLBACK_SEND_ERRORS = (ActionFailed, NetworkError)


async def send_group_message(bot, group_id: int, message: str) -> bool:
    try:
        await bot.call_api(
            "send_group_msg",
            **{
                "message": message,
                "group_id": group_id,
            },
        )
        return True
    except _CALLBACK_SEND_ERRORS as e:
        logger.warning("AI callback send_group_msg failed group={}: {}", group_id, e)
        return False


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
        rec = get_ai_task_record(task_id)
        if rec:
            task = {
                "bot_id": rec.get("bot_id"),
                "group_id": rec.get("group_id"),
            }
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    bot_id = task.get("bot_id")
    group_id = task.get("group_id")

    bot_id_str = str(bot_id).strip() if bot_id is not None else ""
    try:
        bot = get_bot(bot_id_str)
    except Exception as e:
        logger.warning("AI callback get_bot failed task={} bot_id={}: {}", task_id, bot_id_str, e)
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
        if group_id:
            fail_msg = "我习惯了站着不动思考。有时候啊，也会被大家突然戳一戳，看看睡着了没有。"
            if task.get("task_type") == "ollama":
                from src.plugins.ollama.replies import OLLAMA_FAILED_REPLY

                fail_msg = OLLAMA_FAILED_REPLY
            await send_group_message(
                bot,
                group_id,
                fail_msg,
            )
        return {"message": "ok"}

    if status == "success":
        delivered = True
        if text and group_id:
            delivered = await send_group_message(bot, group_id, text) and delivered
        if file and group_id:
            file_content = await file.read()
            base64_file = base64.b64encode(file_content).decode()
            try:
                await bot.call_api(
                    "send_group_msg",
                    **{
                        "message": f"[CQ:record,file=base64://{base64_file}]",
                        "group_id": group_id,
                    },
                )
            except _CALLBACK_SEND_ERRORS as e:
                logger.warning("AI callback send voice failed group={}: {}", group_id, e)
                delivered = False

        await TaskManager.remove_task(task_id)
        remove_ai_task(task_id)
        return {"message": "ok" if delivered else "failed"}

    raise HTTPException(status_code=400, detail="Invalid status")
