"""AI 任务 HTTP 回调执行。"""

from __future__ import annotations

from fastapi import HTTPException, UploadFile
from nonebot import get_bot, logger

from src.features.llm.session_store import append_llm_message
from src.foundation.config import GroupConfig, TaskManager
from src.foundation.db import SingProgress
from src.platform.ai_callback.delivery import send_group_message, send_group_voice
from src.platform.ai_callback.handlers import failure_reply_for_task, should_append_llm_session
from src.platform.shard.coord.ai_task_registry import get_ai_task_record, remove_ai_task


async def resolve_callback_task(task_id: str) -> dict | None:
    task = await TaskManager.get_task(task_id)
    if task:
        return task
    rec = get_ai_task_record(task_id)
    if not rec:
        return None
    return {
        "bot_id": rec.get("bot_id"),
        "group_id": rec.get("group_id"),
    }


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
    task = await resolve_callback_task(task_id)
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
            fail_msg = failure_reply_for_task(task)
            if fail_msg:
                await send_group_message(bot, group_id, fail_msg)
        return {"message": "ok"}

    if status == "success":
        delivered = True
        if text and group_id:
            delivered = await send_group_message(bot, group_id, text) and delivered
        if should_append_llm_session(task) and text:
            raw_group_id = task.get("group_id")
            scope_group = int(raw_group_id) if raw_group_id is not None else None
            speaker_id = int(task.get("user_id") or 0)
            if speaker_id:
                await append_llm_message(int(bot_id), scope_group, speaker_id, "assistant", text)
        if file and group_id:
            delivered = await send_group_voice(bot, group_id, file) and delivered

        await TaskManager.remove_task(task_id)
        remove_ai_task(task_id)
        return {"message": "ok" if delivered else "failed"}

    raise HTTPException(status_code=400, detail="Invalid status")
