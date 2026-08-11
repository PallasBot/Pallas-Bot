"""LLM 回调投递：文本处理、群消息、会话、feedback 与行为记录。"""

from __future__ import annotations

import time
from io import BytesIO
from typing import Any

from nonebot import logger

from pallas.core.foundation.logging.bridge import format_business_event
from pallas.core.platform.ai_callback.delivery import send_group_message
from pallas.core.platform.ai_callback.handlers import (
    should_append_llm_session,
    should_suppress_llm_duplicate_reply,
)
from pallas.core.platform.ai_callback.task_types import (
    LLM_CHAT_TASK_TYPE,
    REPEATER_FALLBACK_TASK_TYPE,
    REPEATER_POLISH_LITE_TASK_TYPE,
    REPEATER_POLISH_TASK_TYPE,
    REPEATER_SELECT_TASK_TYPE,
)
from pallas.product.llm.behavior import BehaviorAction, BehaviorRun, BehaviorScene
from pallas.product.llm.behavior_store import append_behavior_run
from pallas.product.llm.config import get_llm_config
from pallas.product.llm.kernel.memory_governance import can_write_runtime_state_summary
from pallas.product.llm.session_store import append_llm_message, compact_user_llm_history_with_summary
from pallas.product.llm.task_metrics import record_bot_llm_route, record_bot_llm_task

STICKER_IMAGE_MAX_SIDE = 160


def prepare_sticker_image(image_bytes: bytes, *, max_side: int = STICKER_IMAGE_MAX_SIDE) -> bytes:
    """等比缩小表情图片，保留小图和无法处理的原始内容。"""
    from PIL import Image, ImageSequence, UnidentifiedImageError

    try:
        with Image.open(BytesIO(image_bytes)) as image:
            width, height = image.size
            if not width or not height or max(width, height) <= max_side:
                return image_bytes
            scale = max_side / max(width, height)
            size = (max(1, round(width * scale)), max(1, round(height * scale)))
            if image.format == "GIF" and image.n_frames > 1:
                frames = [
                    frame.convert("RGBA").resize(size, Image.Resampling.LANCZOS)
                    for frame in ImageSequence.Iterator(image)
                ]
                durations = [frame.info.get("duration", 0) for frame in ImageSequence.Iterator(image)]
                output = BytesIO()
                frames[0].save(
                    output,
                    format="GIF",
                    save_all=True,
                    append_images=frames[1:],
                    duration=durations,
                    loop=image.info.get("loop", 0),
                    disposal=2,
                )
                return output.getvalue()
            output = BytesIO()
            resized = image.resize(size, Image.Resampling.LANCZOS)
            if image.format == "JPEG" and resized.mode == "RGBA":
                resized = resized.convert("RGB")
            resized.save(output, format=image.format)
            return output.getvalue()
    except (OSError, UnidentifiedImageError):
        return image_bytes


async def send_repeater_emotion_image(
    bot: Any, group_id: int, bot_id: int, user_id: int, user_text: str, *, cooldown_sec: int | None = None
) -> bool:
    """从 Repeater 命中中取一张图片，作为 LLM 回复的第二气泡。"""
    from nonebot.adapters.onebot.v11 import Message, MessageSegment

    from packages.repeater.model import Chat, ChatData
    from pallas.core.shared.utils.media_cache import get_image

    chat = Chat(
        ChatData(
            group_id=int(group_id),
            user_id=int(user_id),
            raw_message=str(user_text or ""),
            plain_text=str(user_text or ""),
            time=int(time.time()),
            bot_id=int(bot_id),
        )
    )
    bundle = await chat.find_reply_bundle()
    if bundle is None:
        return False
    candidates: list[tuple[str, bytes]] = []
    for item in [*bundle.answer_list, *list(getattr(bundle, "message_pool", []) or [])]:
        if "[CQ:image," not in item or any(key == item for key, _data in candidates):
            continue
        for segment in Message(item):
            if segment.type == "image":
                cached = await get_image(str(segment))
                if cached:
                    candidates.append((item, cached))
                break
    if not candidates:
        return False
    raw_image = candidates[0][0]
    from pallas.product.llm.sticker_followup import note_repeater_image_sent, should_send_repeater_image

    cfg = get_llm_config()
    if bool(getattr(cfg, "llm_sticker_vision_enabled", False)):
        from pallas.product.llm.sticker_vision import allow_sticker_vision_enqueue, enqueue_sticker_vision_job

        timeout_sec = float(getattr(cfg, "llm_sticker_vision_timeout_sec", 15.0) or 15.0)
        if allow_sticker_vision_enqueue(int(getattr(cfg, "llm_sticker_vision_max_per_hour", 12) or 0)):
            job_key = f"{int(bot_id)}:{int(group_id)}:{int(time.time() * 1000)}:{hash(raw_image)}"
            try:
                await enqueue_sticker_vision_job(
                    candidates[: int(getattr(cfg, "llm_sticker_vision_candidate_count", 4) or 4)],
                    user_text=user_text,
                    timeout_sec=timeout_sec,
                    idempotency_key=f"sticker_vision.select:{job_key}",
                    bot_id=int(bot_id),
                    group_id=int(group_id),
                    fallback_cq_code=raw_image,
                )
            except Exception as exc:
                logger.debug(format_business_event("视觉表情跟随", "已跳过", group=group_id, error=type(exc).__name__))
            else:
                return True
    configured_cooldown = getattr(cfg, "llm_chat_sticker_cooldown_sec", 90)
    resolved_cooldown = cooldown_sec if cooldown_sec is not None else configured_cooldown
    if not should_send_repeater_image(int(group_id), raw_image, cooldown_sec=int(resolved_cooldown)):
        return False
    message = Message()
    for segment in Message(raw_image):
        if segment.type != "image":
            message += segment
            continue
        cached = await get_image(str(segment))
        if not cached:
            return False
        message += MessageSegment.image(file=prepare_sticker_image(cached))
    try:
        await bot.call_api("send_group_msg", message=message, group_id=int(group_id))
    except Exception as e:
        logger.debug(format_business_event("表情跟随投递", "已跳过", group=group_id, error=type(e).__name__))
        return False
    note_repeater_image_sent(int(group_id), raw_image)
    return True


async def send_cached_sticker_image(bot: Any, group_id: int) -> bool:
    """发送一张本地已缓存的图片，用于验证协议发送链路。"""
    from nonebot.adapters.onebot.v11 import MessageSegment

    from pallas.core.shared.utils.media_cache import get_latest_image

    cached = await get_latest_image()
    if not cached:
        return False
    try:
        await bot.call_api(
            "send_group_msg",
            message=MessageSegment.image(file=prepare_sticker_image(cached)),
            group_id=int(group_id),
        )
    except Exception as e:
        logger.debug(format_business_event("缓存贴纸投递", "已跳过", group=group_id, error=type(e).__name__))
        return False
    return True


_TRACKED_LLM_TASKS = frozenset({
    LLM_CHAT_TASK_TYPE,
    REPEATER_FALLBACK_TASK_TYPE,
    REPEATER_POLISH_TASK_TYPE,
    REPEATER_POLISH_LITE_TASK_TYPE,
    REPEATER_SELECT_TASK_TYPE,
})

_REPEATER_CALLBACK_TASKS = frozenset({
    REPEATER_FALLBACK_TASK_TYPE,
    REPEATER_POLISH_TASK_TYPE,
    REPEATER_POLISH_LITE_TASK_TYPE,
    REPEATER_SELECT_TASK_TYPE,
})

_MENTION_LAST_SENT_AT: dict[int, float] = {}


def resolve_llm_reply_delivery(
    task: dict,
    *,
    group_id: object,
    mention_cooldown_sec: int,
    now: float | None = None,
) -> tuple[int | None, int | None]:
    """Resolve a task's optional QQ reply decoration with local safety gates."""
    if str(task.get("task_type") or "").strip() != LLM_CHAT_TASK_TYPE:
        return None, None
    style = str(task.get("reply_delivery_style") or "PLAIN").strip().upper()
    if style == "QUOTE":
        message_id = task.get("message_id")
        return (int(message_id), None) if str(message_id or "").isdigit() else (None, None)
    if style != "MENTION" or not bool(task.get("has_multi_party_overlap")):
        return None, None
    user_id = task.get("user_id")
    if not str(user_id or "").isdigit() or not str(group_id or "").isdigit():
        return None, None
    resolved_group_id = int(group_id)
    current = time.monotonic() if now is None else now
    if current - _MENTION_LAST_SENT_AT.get(resolved_group_id, float("-inf")) < max(0, mention_cooldown_sec):
        return None, None
    return None, int(user_id)


def note_llm_reply_mention_sent(group_id: object, *, now: float | None = None) -> None:
    if str(group_id or "").isdigit():
        _MENTION_LAST_SENT_AT[int(group_id)] = time.monotonic() if now is None else now


def maybe_append_llm_repeater_feedback(task_id: str, task: dict, reply_text: str) -> None:
    from pallas.product.llm.repeater_feedback import (
        append_feedback_entry,
        build_feedback_entry,
        resolve_feedback_llm_route,
        should_collect_llm_repeater_feedback,
    )

    cfg = get_llm_config()
    if not cfg.llm_repeater_feedback_enabled:
        return
    user_text = str(task.get("user_text") or "").strip()
    source_tags = [str(item).strip() for item in list(task.get("source_tags") or []) if str(item).strip()]
    group_id = int(task.get("group_id") or 0)
    if not should_collect_llm_repeater_feedback(
        task_type=str(task.get("task_type") or "").strip(),
        group_id=group_id,
        user_text=user_text,
        reply_text=reply_text,
        source_tags=source_tags,
        fallback_text=str(task.get("fallback_text") or "").strip(),
    ):
        return
    try:
        task_type = str(task.get("task_type") or "").strip()
        append_feedback_entry(
            build_feedback_entry(
                entry_id=task_id,
                request_id=task_id,
                bot_id=int(task.get("bot_id") or 0),
                group_id=group_id,
                user_id=int(task.get("user_id") or 0),
                user_text=user_text,
                reply_text=reply_text,
                behavior_scene=str(task.get("behavior_scene") or "").strip(),
                scene_tier=str(task.get("scene_tier") or "").strip(),
                behavior_actions=list(task.get("behavior_actions") or []),
                llm_route=resolve_feedback_llm_route(
                    task_type=task_type,
                    llm_route=str(task.get("llm_route") or "").strip(),
                ),
                source_tags=source_tags,
                eligible_for_bias=True,
                eligible_for_writeback=str(task.get("scene_tier") or "").strip().lower() == "strong",
            )
        )
    except Exception as e:
        logger.warning("AI callback append llm_repeater feedback failed task={}: {}", task_id, e)


def track_llm_callback(task: dict, event: str) -> None:
    task_type = str(task.get("task_type") or "").strip()
    if task_type in _TRACKED_LLM_TASKS:
        record_bot_llm_task(task_type, event)
        if event == "callback_ok":
            from pallas.product.llm.repeater_feedback import resolve_feedback_llm_route

            record_bot_llm_route(
                task_type,
                resolve_feedback_llm_route(
                    task_type=task_type,
                    llm_route=str(task.get("llm_route") or "").strip(),
                ),
            )


async def evaluate_repeater_callback_text(task: dict, reply_text: str) -> bool:
    task_type = str(task.get("task_type") or "").strip()
    if task_type not in _REPEATER_CALLBACK_TASKS:
        return True
    from packages.repeater.responder import Responder

    text = str(reply_text or "").strip()
    if not text:
        return False
    fallback = str(task.get("fallback_text") or "").strip()
    if fallback and text == fallback:
        return True
    bot_id = int(task.get("bot_id") or 0)
    group_id = int(task.get("group_id") or 0)
    user_text = str(task.get("user_text") or "").strip()
    reply_mode = str(task.get("reply_mode") or "normal").strip().lower() or "normal"
    recent_sent = []
    persona = None
    affect_triggers = None
    if bot_id and group_id:
        try:
            from pallas.product.persona import resolve_persona_for_message
            from pallas.product.persona.loader import load_affect_triggers

            persona = await resolve_persona_for_message(bot_id, group_id, user_text or text)
            affect_triggers = await load_affect_triggers(group_id)
        except Exception:
            persona = None
            affect_triggers = None
    accepted, _score = Responder.evaluate_llm_candidate_text(
        text,
        base_score=0.8,
        min_score=0.55,
        recent_sent=recent_sent,
        persona=persona,
        affect_triggers=affect_triggers,
        reply_mode=reply_mode,
    )
    return accepted


async def deliver_llm_callback_success(
    task_id: str,
    task: dict,
    *,
    bot: Any,
    group_id: Any,
    bot_id: Any,
    bot_id_str: str,
    text: str | None,
    parsed_agent_trace: dict | None,
    history_summary: str | None,
    history_keep_messages: int | None,
    suppress_empty_fallback: bool = False,
) -> tuple[str, bool, bool]:
    """处理 LLM 回调文本并投递到群。返回 (reply_text, text_delivered, delivered)。"""
    delivered = bot is not None
    reply_text = str(text or "").strip()
    text_delivered = False
    task_type = str(task.get("task_type") or "").strip()
    if task_type == REPEATER_SELECT_TASK_TYPE:
        from pallas.product.llm.select import resolve_select_callback_text

        pool = task.get("candidate_pool") or []
        fallback = str(task.get("fallback_text") or "").strip()
        reply_text = resolve_select_callback_text(reply_text, pool, fallback)
    elif should_suppress_llm_duplicate_reply(task, reply_text):
        fallback = str(task.get("fallback_text") or "").strip()
        reply_text = fallback if fallback and fallback != reply_text else ""
    from pallas.product.llm.output_filter import resolve_output_filtered_reply

    had_reply_before_filter = bool(reply_text)
    reply_text = resolve_output_filtered_reply(task, reply_text)
    if task_type == LLM_CHAT_TASK_TYPE and reply_text:
        from pallas.product.llm.message_guard import strip_leading_self_at_mentions
        from pallas.product.persona.self_identity import DEFAULT_SELF_ALIASES

        raw_aliases = task.get("self_aliases")
        mention_names = (
            [str(item) for item in raw_aliases if str(item).strip()]
            if isinstance(raw_aliases, list) and raw_aliases
            else list(DEFAULT_SELF_ALIASES)
        )
        bot_id_raw = task.get("bot_id")
        bot_self_id = int(bot_id_raw) if bot_id_raw is not None and str(bot_id_raw).isdigit() else None
        reply_text = strip_leading_self_at_mentions(
            reply_text,
            bot_self_id=bot_self_id,
            mention_names=mention_names,
        )
    if task_type == LLM_CHAT_TASK_TYPE and not had_reply_before_filter:
        from pallas.product.llm.chat_empty_fallback import resolve_llm_chat_empty_fallback

        reply_text = resolve_llm_chat_empty_fallback(
            task,
            reply_text,
            suppress_empty_fallback=suppress_empty_fallback,
        )
    if task_type in _REPEATER_CALLBACK_TASKS and reply_text:
        accepted = await evaluate_repeater_callback_text(task, reply_text)
        if not accepted:
            fallback = str(task.get("fallback_text") or "").strip()
            if fallback and fallback != reply_text and await evaluate_repeater_callback_text(task, fallback):
                reply_text = fallback
            else:
                reply_text = ""
    learned_reply_text = reply_text
    reply_segments = [reply_text] if reply_text else []
    if reply_text:
        from pallas.product.llm.reply_postprocess import apply_reply_postprocess

        cfg = get_llm_config()
        reply_segments = apply_reply_postprocess(
            reply_text,
            enabled=bool(cfg.llm_reply_postprocess_enabled),
            typo_enabled=bool(cfg.llm_reply_typo_enabled),
            typo_rate=float(cfg.llm_reply_typo_rate),
            split_enabled=bool(cfg.llm_reply_split_enabled),
            split_max_chars=int(cfg.llm_reply_split_max_chars),
            trim_terminal_period_enabled=bool(cfg.llm_reply_trim_terminal_period_enabled),
            trim_terminal_period_rate=float(cfg.llm_reply_trim_terminal_period_rate),
        )
        reply_text = "".join(reply_segments)
    if reply_segments and group_id and bot is not None:
        logger.info(
            "AI callback delivering text task={} bot_id={} group_id={} length={} segments={} task_type={}",
            task_id,
            getattr(bot, "self_id", bot_id_str or "<missing>"),
            group_id,
            len(reply_text),
            len(reply_segments),
            task_type,
        )
        text_delivered = True
        reply_to_message_id, at_user_id = resolve_llm_reply_delivery(
            task,
            group_id=group_id,
            mention_cooldown_sec=int(cfg.llm_reply_mention_cooldown_sec),
        )
        for index, segment in enumerate(reply_segments):
            ok = await send_group_message(
                bot,
                group_id,
                segment,
                reply_to_message_id=reply_to_message_id if index == 0 else None,
                at_user_id=at_user_id if index == 0 else None,
            )
            if index == 0 and ok and at_user_id is not None:
                note_llm_reply_mention_sent(group_id)
            text_delivered = bool(ok) and text_delivered
        delivered = text_delivered and delivered
    if should_append_llm_session(task) and learned_reply_text:
        raw_group_id = task.get("group_id")
        scope_group = int(raw_group_id) if raw_group_id is not None else None
        speaker_id = int(task.get("user_id") or 0)
        user_text = str(task.get("user_text") or "").strip()
        if speaker_id:
            if history_summary and history_keep_messages and can_write_runtime_state_summary():
                await compact_user_llm_history_with_summary(
                    int(bot_id),
                    scope_group,
                    speaker_id,
                    history_summary,
                    keep_messages=int(history_keep_messages),
                )
            if user_text:
                await append_llm_message(int(bot_id), scope_group, speaker_id, "user", user_text)
            await append_llm_message(int(bot_id), scope_group, speaker_id, "assistant", learned_reply_text)
            from pallas.product.llm.memory.auto_episode import schedule_auto_save_group_episode

            schedule_auto_save_group_episode(bot_id=int(bot_id), group_id=scope_group)
    from pallas.product.llm.repeater_feedback import is_feedback_task_type

    if is_feedback_task_type(task_type) and learned_reply_text and text_delivered:
        maybe_append_llm_repeater_feedback(task_id, task, learned_reply_text)
    if learned_reply_text and text_delivered and group_id:
        scene_tier = str(task.get("scene_tier") or "").strip()
        channel = "at_chat" if task_type == LLM_CHAT_TASK_TYPE else "strong" if scene_tier == "strong" else "group"
        try:
            from pallas.product.persona.expression_learn import note_expression_from_utterance

            note_expression_from_utterance(
                int(group_id),
                learned_reply_text,
                source="llm_success",
                channel=channel,
                scene_tier=scene_tier,
                bot_id=int(bot_id or 0),
            )
        except Exception as exc:
            logger.debug("AI callback expression learn skipped task={}: {}", task_id, exc)
    if learned_reply_text and text_delivered:
        if bool(get_llm_config().llm_reply_effect_eval_enabled):
            from pallas.product.llm.reply_effect import evaluate_and_record_reply_effect

            try:
                evaluate_and_record_reply_effect(
                    learned_reply_text,
                    task_type=task_type,
                    group_id=int(group_id) if group_id is not None else None,
                    user_id=int(task.get("user_id") or 0) or None,
                )
            except Exception:
                logger.debug("reply effect eval skipped task={}", task_id)
    behavior_scene = str(task.get("behavior_scene") or "").strip()
    if task_type == LLM_CHAT_TASK_TYPE and behavior_scene:
        append_behavior_run(
            BehaviorRun(
                request_id=task_id,
                bot_id=int(bot_id) if bot_id is not None else None,
                group_id=int(group_id) if group_id is not None else None,
                user_id=int(task.get("user_id") or 0) or None,
                created_at=int(time.time()),
                scene=BehaviorScene(behavior_scene),
                user_text=str(task.get("user_text") or "").strip(),
                reply_text=learned_reply_text,
                selected_pattern_ids=[
                    str(item) for item in list(task.get("behavior_pattern_ids") or []) if str(item).strip()
                ],
                selected_actions=[
                    BehaviorAction(str(item)) for item in list(task.get("behavior_actions") or []) if str(item).strip()
                ],
                selected_expression_ids=[
                    str(item) for item in list(task.get("selected_expression_ids") or []) if str(item).strip()
                ],
                selected_catchphrase_ids=[
                    str(item) for item in list(task.get("selected_catchphrase_ids") or []) if str(item).strip()
                ],
                behavior_hint_text=str(task.get("behavior_hint") or "").strip(),
                auto_feedback_payload={"agent_trace": parsed_agent_trace} if parsed_agent_trace else {},
            )
        )
    track_llm_callback(task, "callback_ok")
    return reply_text, text_delivered, delivered


async def deliver_llm_chat_result(
    task_id: str,
    *,
    status: str,
    text: str | None = None,
    agent_trace: str | None = None,
    history_summary: str | None = None,
    history_keep_messages: int | None = None,
    suppress_empty_fallback: bool = False,
) -> dict[str, str]:
    """闲聊结果投递（内核直连与 AI HTTP 回调共用）。"""
    from pallas.core.platform.ai_callback.runner import run_ai_callback

    return await run_ai_callback(
        task_id,
        status=status,
        text=text,
        agent_trace=agent_trace,
        history_summary=history_summary,
        history_keep_messages=history_keep_messages,
        suppress_empty_fallback=suppress_empty_fallback,
    )
