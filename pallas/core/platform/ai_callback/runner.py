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
from pallas.product.llm.delivery import deliver_llm_callback_success, track_llm_callback
from pallas.product.llm.turn_telemetry import record_turn_event

# 注意：runner 是协调 LLM 回调投递的平台执行层，与 product.llm 投递语义天然耦合，
# 与 core/runtime/boot.py 同理属合理的产品-平台接线，不纳入 core→product 编译期依赖收敛目标。

__all__ = [
    "resolve_callback_task",
    "run_ai_callback",
]


def __getattr__(name: str):
    """惰性提供兼容性重导出符号（历史上曾列于 __all__，现无消费方），避免模块级导入。"""
    if name == "deliver_llm_chat_result":
        from pallas.product.llm.delivery import deliver_llm_chat_result

        return deliver_llm_chat_result
    if name == "maybe_append_llm_repeater_feedback":
        from pallas.product.llm.delivery import maybe_append_llm_repeater_feedback

        return maybe_append_llm_repeater_feedback
    raise AttributeError(name)


async def resolve_callback_task(task_id: str) -> dict | None:
    """原子领取回调任务；重复回调将拿不到任务（404），避免重复发语音/图。"""
    task = await TaskManager.claim_task(task_id)
    if task:
        return task
    rec = claim_ai_task_record(task_id)
    if not rec:
        return None
    return dict(rec)


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
    suppress_empty_fallback: bool = False,
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
        logger.warning("AI callback failed to get bot [{}] for task [{}]: [{}].", bot_id_str, task_id, e)
    logger.info(
        f"Bot [{bot_id_str or '<missing>'}] resolved AI task [{task_id}], "
        f"a [{str(task.get('task_type') or '').strip()}] request in group [{group_id}], status [{status}]"
    )
    logger.debug(
        "AI callback resolved task [{}] with text [{}], file [{}], song [{}], chunk [{}], "
        "key [{}], history summary [{}], retained history messages [{}], and agent trace [{}].",
        task_id,
        bool(str(text or "").strip()),
        file is not None,
        song_id,
        chunk_index,
        key,
        bool(history_summary),
        history_keep_messages,
        bool(agent_trace),
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
        turn_id = str(task.get("turn_id") or "").strip()
        if turn_id:
            try:
                record_turn_event(
                    turn_id=turn_id,
                    stage="output",
                    decision="failed",
                    reason="callback_failed",
                    text="",
                    message_id=task.get("message_id"),
                    request_id=task_id,
                    scope={
                        "bot": task.get("bot_id"),
                        "group": task.get("group_id"),
                        "user": task.get("user_id"),
                    },
                    is_to_me=bool(task.get("is_to_me", False)),
                    speak_trigger=str(task.get("speak_trigger") or "") or None,
                )
            except Exception:
                logger.debug("LLM callback failure telemetry skipped for task [{}]", task_id)
        track_llm_callback(task, "callback_fail")
        invoke_media_task_failure(task)
        if bot is not None and group_id:
            fail_msg = failure_reply_for_task(task)
            if fail_msg:
                logger.info(
                    "AI callback is sending failure reply for task [{}] from bot [{}] to group [{}] with length [{}].",
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
            suppress_empty_fallback=suppress_empty_fallback,
        )
        task_type = str(task.get("task_type") or "").strip()
        if file and group_id and bot is not None:
            file_bytes = await file.read()
            logger.debug(
                "AI callback read file for task [{}] from bot [{}] in group [{}]; type [{}], "
                "bytes [{}], song [{}], chunk [{}], key [{}].",
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
                    f"Bot [{getattr(bot, 'self_id', bot_id_str or '<missing>')}] delivering a "
                    f"[{task_type}] image [{task_id}] to group [{group_id}], length [{len(file_bytes)}]"
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
                    f"Bot [{getattr(bot, 'self_id', bot_id_str or '<missing>')}] delivering a "
                    f"[{task_type}] voice [{task_id}] to group [{group_id}], length [{len(file_bytes)}]"
                )
                delivered = await send_group_voice(bot, group_id, file_bytes) and delivered
                if delivered and file_bytes:
                    invoke_media_task_success(task, image_bytes=file_bytes, group_id=int(group_id))

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
                logger.exception("Enqueuing drunk TTS failed for task [{}].", task_id)

        logger.info(
            f"Bot [{bot_id_str or '<missing>'}] completed AI task [{task_id}], "
            f"a [{str(task.get('task_type') or '').strip()}] request in group [{group_id}], delivered [{delivered}]"
        )
        return {"message": "ok" if delivered else "failed"}

    raise HTTPException(status_code=400, detail="Invalid status")
