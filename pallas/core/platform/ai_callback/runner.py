"""AI 任务 HTTP 回调执行。"""

from __future__ import annotations

import json

from fastapi import HTTPException, UploadFile
from nonebot import get_bot, logger

from pallas.core.foundation.config import GroupConfig, TaskManager
from pallas.core.foundation.db import SingProgress
from pallas.core.platform.ai_callback.delivery import send_group_image, send_group_message, send_group_voice
from pallas.core.platform.ai_callback.handlers import failure_reply_for_task
from pallas.core.platform.ai_callback.media_task_hooks import (
    invoke_media_task_failure,
    invoke_media_task_success,
)
from pallas.core.platform.ai_callback.task_types import (
    CHAT_DRUNK_TASK_TYPE,
    DRAW_IMAGE_TASK_TYPE,
    VOICE_TASK_TYPES,
)
from pallas.core.platform.shard.coord.ai_task_registry import claim_ai_task_record
from pallas.product.llm.delivery import (
    deliver_llm_callback_success,
    deliver_llm_chat_result,
    evaluate_repeater_callback_text,
    maybe_append_llm_repeater_feedback,
    track_llm_callback,
)

__all__ = [
    "deliver_llm_chat_result",
    "evaluate_repeater_callback_text",
    "maybe_append_llm_repeater_feedback",
    "resolve_callback_task",
    "run_ai_callback",
]


async def resolve_callback_task(task_id: str) -> dict | None:
    """原子领取回调任务；重复回调将拿不到任务（404），避免重复发语音/图。"""
    task = await TaskManager.claim_task(task_id)
    if task:
        return task
    rec = claim_ai_task_record(task_id)
    if not rec:
        return None
    return {
        "bot_id": rec.get("bot_id"),
        "group_id": rec.get("group_id"),
        "user_id": rec.get("user_id"),
        "task_type": rec.get("task_type"),
        "user_text": rec.get("user_text"),
        "fallback_text": rec.get("fallback_text"),
        "candidate_pool": rec.get("candidate_pool"),
        "llm_route": rec.get("llm_route"),
        "behavior_scene": rec.get("behavior_scene"),
        "last_reply_text": rec.get("last_reply_text"),
        "recent_reply_texts": rec.get("recent_reply_texts"),
    }


async def run_ai_callback(
    task_id: str,
    *,
    status: str,
    text: str | None = None,
    agent_trace: str | None = None,
    song_id: str | None = None,
    chunk_index: int | None = None,
    key: int | None = None,
    file: UploadFile | None = None,
    history_summary: str | None = None,
    history_keep_messages: int | None = None,
) -> dict[str, str]:
    task = await resolve_callback_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    parsed_agent_trace: dict | None = None
    if agent_trace:
        try:
            raw_trace = json.loads(agent_trace)
        except json.JSONDecodeError:
            raw_trace = None
        if isinstance(raw_trace, dict):
            parsed_agent_trace = raw_trace
            task["agent_trace"] = raw_trace
            from pallas.product.llm.runtime_debug import append_runtime_trace

            append_runtime_trace(request_id=task_id, trace=raw_trace)

    bot_id = task.get("bot_id")
    group_id = task.get("group_id")

    bot_id_str = str(bot_id).strip() if bot_id is not None else ""
    bot = None
    try:
        bot = get_bot(bot_id_str)
    except Exception as e:
        logger.warning("AI callback get_bot failed task={} bot_id={}: {}", task_id, bot_id_str, e)
    logger.info(
        (
            "AI callback resolved task={} status={} task_type={} bot_id={} group_id={} "
            "has_text={} has_file={} song_id={} chunk_index={} key={} history_summary={} "
            "history_keep_messages={} agent_trace={}"
        ),
        task_id,
        status,
        str(task.get("task_type") or "").strip(),
        bot_id_str or "<missing>",
        group_id,
        bool(str(text or "").strip()),
        file is not None,
        song_id,
        chunk_index,
        key,
        bool(history_summary),
        history_keep_messages,
        bool(parsed_agent_trace),
    )

    if group_id and song_id is not None and chunk_index is not None and key is not None and bot is not None:
        config = GroupConfig(group_id)
        sing_progress = SingProgress(
            song_id=str(song_id),
            chunk_index=chunk_index,
            key=key,
        )
        await config.update_sing_progress(sing_progress)

    if status == "failed":
        track_llm_callback(task, "callback_fail")
        invoke_media_task_failure(task)
        if bot is not None and group_id:
            fail_msg = failure_reply_for_task(task)
            if fail_msg:
                logger.info(
                    "AI callback sending failure reply task={} bot_id={} group_id={} length={}",
                    task_id,
                    getattr(bot, "self_id", bot_id_str or "<missing>"),
                    group_id,
                    len(fail_msg),
                )
                await send_group_message(bot, group_id, fail_msg)
        return {"message": "ok"}

    if status == "success":
        reply_text, text_delivered, delivered = await deliver_llm_callback_success(
            task_id,
            task,
            bot=bot,
            group_id=group_id,
            bot_id=bot_id,
            bot_id_str=bot_id_str,
            text=text,
            parsed_agent_trace=parsed_agent_trace,
            history_summary=history_summary,
            history_keep_messages=history_keep_messages,
        )
        task_type = str(task.get("task_type") or "").strip()
        if file and group_id and bot is not None:
            file_bytes = await file.read()
            logger.info(
                (
                    "AI callback read file task={} bot_id={} group_id={} task_type={} "
                    "bytes={} song_id={} chunk_index={} key={}"
                ),
                task_id,
                getattr(bot, "self_id", bot_id_str or "<missing>"),
                group_id,
                task_type,
                len(file_bytes),
                song_id,
                chunk_index,
                key,
            )
            if task_type == DRAW_IMAGE_TASK_TYPE:
                at_user = task.get("user_id")
                at_user_id = int(at_user) if at_user is not None else None
                logger.info(
                    "AI callback delivering image task={} bot_id={} group_id={} at_user_id={} bytes={}",
                    task_id,
                    getattr(bot, "self_id", bot_id_str or "<missing>"),
                    group_id,
                    at_user_id,
                    len(file_bytes),
                )
                delivered = (
                    await send_group_image(
                        bot,
                        group_id,
                        file_bytes,
                        at_user_id=at_user_id,
                    )
                    and delivered
                )
                if delivered and file_bytes:
                    invoke_media_task_success(task, image_bytes=file_bytes, group_id=int(group_id))
            elif task_type in VOICE_TASK_TYPES or (song_id is not None and chunk_index is not None):
                logger.info(
                    (
                        "AI callback delivering voice task={} bot_id={} group_id={} task_type={} "
                        "bytes={} song_id={} chunk_index={} key={}"
                    ),
                    task_id,
                    getattr(bot, "self_id", bot_id_str or "<missing>"),
                    group_id,
                    task_type,
                    len(file_bytes),
                    song_id,
                    chunk_index,
                    key,
                )
                delivered = await send_group_voice(bot, group_id, file_bytes) and delivered

        if (
            task_type == CHAT_DRUNK_TASK_TYPE
            and task.get("want_tts")
            and not task.get("voice_only")
            and reply_text
            and text_delivered
            and file is None
            and group_id is not None
            and bot_id is not None
        ):
            from pallas.product.llm.drunk_tts import enqueue_ai_drunk_tts, should_attach_drunk_tts

            try:
                if await should_attach_drunk_tts(
                    bot_id=bot_id,
                    group_id=int(group_id),
                    reply_text=reply_text,
                ):
                    await enqueue_ai_drunk_tts(
                        bot_id=bot_id_str or bot_id or "",
                        group_id=int(group_id),
                        user_id=int(task.get("user_id") or 0) or None,
                        text=reply_text,
                    )
            except Exception:
                logger.exception("enqueue drunk tts failed task={}", task_id)

        logger.info(
            "AI callback completed task={} delivered={} bot_id={} group_id={} task_type={}",
            task_id,
            delivered,
            bot_id_str or "<missing>",
            group_id,
            str(task.get("task_type") or "").strip(),
        )
        return {"message": "ok" if delivered else "failed"}

    raise HTTPException(status_code=400, detail="Invalid status")
