"""LLM 回调投递：文本处理、群消息、会话、feedback 与行为记录。"""

from __future__ import annotations

import asyncio
import inspect
import random
import re
import time
from contextlib import nullcontext
from io import BytesIO
from typing import TYPE_CHECKING, Any

from nonebot import logger

from pallas.api.logging import format_plugin_event
from pallas.core.foundation.logging import log_rate_limited
from pallas.core.foundation.logging.bridge import format_business_event
from pallas.core.platform.ai_callback.handlers import (
    should_append_llm_session,
    should_suppress_llm_duplicate_reply,
)
from pallas.core.platform.ai_callback.task_types import LLM_CHAT_TASK_TYPE
from pallas.product.llm.behavior import BehaviorAction, BehaviorRun, BehaviorScene
from pallas.product.llm.behavior_store import append_behavior_run
from pallas.product.llm.config import get_llm_config
from pallas.product.llm.kernel.memory_governance import can_write_runtime_state_summary
from pallas.product.llm.session_store import append_llm_message, compact_user_llm_history_with_summary
from pallas.product.llm.task_metrics import record_bot_llm_route, record_bot_llm_task

STICKER_IMAGE_MAX_SIDE = 320
_STICKER_JPEG_QUALITY = 90

_STICKER_MARKER_RE = re.compile(r"\[表情[：:]\s*([^\]\n]{1,24})\]\s*$")


def extract_sticker_marker(text: str) -> tuple[str, str]:
    """若文本末尾是 [表情：XX] 标记，返回 (去掉标记的正文, 表情词)；否则返回 (原文本, '')。"""
    plain = str(text or "").strip()
    if not plain:
        return plain, ""
    match = _STICKER_MARKER_RE.search(plain)
    if match is None:
        return plain, ""
    intent = match.group(1).strip()
    body = (plain[: match.start()] + plain[match.end() :]).strip(" \t\n")
    return body, intent


def marker_to_sticker_tokens(intent: str) -> str:
    """把 [表情：得意] 里的词映射成表情挑选器识别的 emotion:/action:/tone: 意图串。"""
    from pallas.product.llm.sticker_labels import (
        ACTION_VOCABULARY,
        EMOTION_VOCABULARY,
        TONE_VOCABULARY,
    )

    parts: list[str] = []
    for key, vocabulary in (
        ("emotion", EMOTION_VOCABULARY),
        ("action", ACTION_VOCABULARY),
        ("tone", TONE_VOCABULARY),
    ):
        parts.extend(f"{key}:{word}" for word in vocabulary if word in intent)
    return " ".join(parts) or f"usage:{intent[:160]}"


if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable


def bubble_delay_seconds(previous_segment: str, *, rng: random.Random | None = None) -> float:
    """Simulate a human pause between chat bubbles: short lines fire fast, long lines linger.

    Base grows with segment length (short ~0.8s, long ~2.7s), then a ±jitter is
    applied, clamped to [0.5, 3.5] seconds so bursts never feel robotic or too slow.
    The base/per-char/jitter values come from LLM config (see llama bubble-delay
    settings); defaults match the long-standing hardcoded rhythm.
    """
    cfg = get_llm_config()
    base_per_char = float(getattr(cfg, "llm_bubble_delay_per_char", 0.04))
    jitter_margin = float(getattr(cfg, "llm_bubble_delay_jitter", 0.35))
    base = float(getattr(cfg, "llm_bubble_delay_base_sec", 0.8))
    length = min(len(str(previous_segment or "").strip()), 48)
    base = base + length * base_per_char
    jitter = (rng or random).uniform(1.0 - jitter_margin, 1.0 + jitter_margin)
    return round(max(0.5, min(3.5, base * jitter)), 2)


async def sleep_between_bubbles(
    delay: float,
    sleeper: Callable[[float], Awaitable[None] | None],
) -> None:
    result = sleeper(delay)
    if inspect.isawaitable(result):
        await result


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
            if image.format == "JPEG":
                if resized.mode == "RGBA":
                    resized = resized.convert("RGB")
                resized.save(
                    output,
                    format="JPEG",
                    quality=_STICKER_JPEG_QUALITY,
                    subsampling=0,
                    optimize=True,
                )
            elif image.format == "PNG":
                resized.save(output, format="PNG", optimize=True)
            else:
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
    from pallas.product.llm.sticker_followup import (
        note_repeater_image_sent,
        recent_repeater_image_hashes,
        should_send_repeater_image,
    )
    from pallas.product.llm.sticker_labels import content_hash_for_bytes
    from pallas.product.llm.sticker_selector import should_refine_with_vision

    ranked, labels = await rank_cached_sticker_candidates(
        user_text,
        candidates,
        recent_hashes=recent_repeater_image_hashes(int(group_id)),
    )
    if not ranked:
        return False
    raw_image = ranked[0].candidate.cq_code

    cfg = get_llm_config()
    if bool(getattr(cfg, "llm_sticker_vision_enabled", False)) and should_refine_with_vision(ranked, labels):
        from pallas.product.llm.sticker_vision import allow_sticker_vision_enqueue, enqueue_sticker_vision_job

        timeout_sec = float(getattr(cfg, "llm_sticker_vision_timeout_sec", 15.0) or 15.0)
        if allow_sticker_vision_enqueue(int(getattr(cfg, "llm_sticker_vision_max_per_hour", 12) or 0)):
            candidate_by_code = dict(candidates)
            vision_candidates = [
                (item.candidate.cq_code, candidate_by_code[item.candidate.cq_code])
                for item in ranked[: int(getattr(cfg, "llm_sticker_vision_candidate_count", 4) or 4)]
            ]
            job_key = f"{int(bot_id)}:{int(group_id)}:{int(time.time() * 1000)}:{hash(raw_image)}"
            try:
                await enqueue_sticker_vision_job(
                    vision_candidates,
                    user_text=user_text,
                    timeout_sec=timeout_sec,
                    idempotency_key=f"sticker_vision.select:{job_key}",
                    bot_id=int(bot_id),
                    group_id=int(group_id),
                    fallback_cq_code=raw_image,
                    cooldown_sec=int(
                        cooldown_sec if cooldown_sec is not None else getattr(cfg, "llm_chat_sticker_cooldown_sec", 90)
                    ),
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
        message += MessageSegment.image(file=cached)
    try:
        await bot.call_api("send_group_msg", message=message, group_id=int(group_id))
    except Exception as e:
        logger.debug(format_business_event("表情跟随投递", "已跳过", group=group_id, error=type(e).__name__))
        return False
    note_repeater_image_sent(int(group_id), raw_image, content_hash=content_hash_for_bytes(cached))
    return True


def _consume_sticker_label_enqueue_result(task: asyncio.Task[bool]) -> None:
    try:
        task.result()
    except Exception as exc:
        logger.debug("sticker label enqueue skipped: {}", exc)


async def rank_cached_sticker_candidates(
    intent: str,
    candidates: list[tuple[str, bytes]],
    *,
    recent_hashes: tuple[str, ...] = (),
    source: object | None = None,
):
    """读取已有标签并懒入队缺失标签，不等待视觉标注任务。"""
    from pallas.product.llm.sticker_label_jobs import (
        StickerLabelSource,
        enqueue_sticker_label_candidate,
        sticker_label_repository,
    )
    from pallas.product.llm.sticker_labels import content_hash_for_bytes
    from pallas.product.llm.sticker_selector import StickerCandidate, rank_sticker_candidates

    resolved_source = source if isinstance(source, StickerLabelSource) else StickerLabelSource.FOLLOWUP_CANDIDATE
    candidate_by_hash: dict[str, tuple[str, bytes]] = {}
    for cq_code, image in candidates:
        candidate_by_hash.setdefault(content_hash_for_bytes(image), (cq_code, image))
    labels = {}
    repository = sticker_label_repository()
    for content_hash, (cq_code, image) in candidate_by_hash.items():
        try:
            label = await repository.get(content_hash)
        except Exception as exc:
            logger.debug("sticker label lookup skipped: {}", exc)
            label = None
        if label is None:
            followup_task = asyncio.create_task(
                enqueue_sticker_label_candidate(cache_key=cq_code, content=image, source=resolved_source),
                name=f"sticker_label_followup:{content_hash[:12]}",
            )
            followup_task.add_done_callback(_consume_sticker_label_enqueue_result)
        else:
            labels[content_hash] = label
    return (
        rank_sticker_candidates(
            intent,
            [StickerCandidate(cq_code, content_hash_for_bytes(image)) for cq_code, image in candidates],
            labels,
            recent_hashes=recent_hashes,
        ),
        labels,
    )


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
            message=MessageSegment.image(file=cached),
            group_id=int(group_id),
        )
    except Exception as e:
        logger.debug(format_business_event("缓存贴纸投递", "已跳过", group=group_id, error=type(e).__name__))
        return False
    return True


_TRACKED_LLM_TASKS = frozenset({LLM_CHAT_TASK_TYPE})

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
        return _resolve_quote_reply_target(task)
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


def _resolve_quote_reply_target(task: dict) -> tuple[int | None, int | None]:
    """Quote only an offered candidate id recorded in the task; unknown ids degrade to plain."""
    selected = task.get("reply_to_message_id")
    selected_id = int(selected) if str(selected or "").isdigit() else None
    candidate_ids = {int(item) for item in list(task.get("reply_candidate_ids") or []) if str(item or "").isdigit()}
    if selected_id is not None and selected_id in candidate_ids:
        return selected_id, None
    return None, None


def note_llm_reply_mention_sent(group_id: object, *, now: float | None = None) -> None:
    if str(group_id or "").isdigit():
        _MENTION_LAST_SENT_AT[int(group_id)] = time.monotonic() if now is None else now


def maybe_append_llm_repeater_feedback(
    task_id: str,
    task: dict,
    reply_text: str,
    *,
    bot_message_id: int | None = None,
    semantic_source_bound: bool = False,
) -> None:
    from pallas.product.llm.repeater_feedback import (
        append_feedback_entry,
        build_feedback_entry,
        feedback_reply_max_len,
        normalize_feedback_llm_route,
        should_collect_llm_repeater_feedback,
    )

    cfg = get_llm_config()
    if not cfg.llm_repeater_feedback_enabled:
        return
    user_text = str(task.get("user_text") or "").strip()
    source_tags = [str(item).strip() for item in list(task.get("source_tags") or []) if str(item).strip()]
    group_id = int(task.get("group_id") or 0)
    direct_candidate = str(task.get("semantic_style_direct_candidate") or "").strip()
    semantic_source_example_id = str(task.get("semantic_style_source_example_id") or "").strip()
    if not semantic_source_bound or not direct_candidate or str(reply_text or "").strip() != direct_candidate:
        semantic_source_example_id = ""
    task_type = str(task.get("task_type") or "").strip()
    collect_for_learning = should_collect_llm_repeater_feedback(
        task_type=task_type,
        group_id=group_id,
        user_text=user_text,
        reply_text=reply_text,
        source_tags=source_tags,
    )
    retain_for_message_lookup = bool(
        task_type == LLM_CHAT_TASK_TYPE
        and group_id > 0
        and int(bot_message_id or 0) > 0
        and str(reply_text or "").strip()
    )
    if not collect_for_learning and not retain_for_message_lookup:
        return
    reply_preview = str(reply_text or "").strip()[: feedback_reply_max_len(task_type=task_type)].rstrip()
    if not collect_for_learning:
        semantic_source_example_id = ""
    try:
        append_feedback_entry(
            build_feedback_entry(
                entry_id=task_id,
                request_id=task_id,
                bot_id=int(task.get("bot_id") or 0),
                group_id=group_id,
                user_id=int(task.get("user_id") or 0),
                user_text=user_text,
                reply_text=reply_preview,
                behavior_scene=str(task.get("behavior_scene") or "").strip(),
                scene_tier=str(task.get("scene_tier") or "").strip(),
                behavior_actions=list(task.get("behavior_actions") or []),
                llm_route=normalize_feedback_llm_route(task.get("llm_route")),
                source_tags=source_tags,
                eligible_for_bias=collect_for_learning,
                bot_message_id=int(bot_message_id or 0),
                semantic_source_example_id=semantic_source_example_id,
                semantic_scene="group_chat",
                injection_snapshot=task.get("injection_snapshot"),
            )
        )
    except Exception as e:
        logger.warning("AI callback append llm_repeater feedback failed for task [{}], error [{}]", task_id, e)


def semantic_source_matches_delivery(
    task: dict,
    *,
    reply_segments: list[str],
    bot_message_id: int | None,
    text_delivered: bool,
) -> bool:
    candidate = str(task.get("semantic_style_direct_candidate") or "").strip()
    return bool(
        len(reply_segments) == 1 and bot_message_id and text_delivered and str(reply_segments[0]).strip() == candidate
    )


def resolve_llm_reply_route(task: dict) -> str:
    """把 llm_chat 任务映射到回复路径桶：@直出 / 别名感知 / 主动发言 / 续聊。"""
    from pallas.product.llm.repeater_feedback import normalize_feedback_llm_route

    llm_route = normalize_feedback_llm_route(task.get("llm_route"))
    if llm_route and llm_route != "plain_llm_chat":
        return llm_route
    trigger = str(task.get("speak_trigger") or "").strip().lower()
    if trigger in {"alias", "mention"}:
        return "alias"
    if trigger == "ambient":
        return "ambient"
    if trigger == "followup":
        return "followup"
    return "plain_llm_chat"


def track_llm_callback(task: dict, event: str) -> None:
    task_type = str(task.get("task_type") or "").strip()
    if task_type in _TRACKED_LLM_TASKS:
        record_bot_llm_task(task_type, event)
        if event == "callback_ok":
            record_bot_llm_route(task_type, resolve_llm_reply_route(task))


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
    sleeper: Callable[[float], Awaitable[None] | None] | None = None,
) -> tuple[str, bool, bool]:
    """处理 LLM 回调文本并投递到群。返回 (reply_text, text_delivered, delivered)。"""
    delivered = bot is not None
    reply_text = str(text or "").strip()
    text_delivered = False
    bot_message_id: int | None = None
    task_type = str(task.get("task_type") or "").strip()
    if should_suppress_llm_duplicate_reply(task, reply_text):
        fallback = str(task.get("fallback_text") or "").strip()
        reply_text = fallback if fallback and fallback != reply_text else ""
    marker_intent = ""
    from pallas.product.llm.models import StructuredChatReply
    from pallas.product.llm.output_filter import profile_for_task_type, resolve_output_filtered_chat_reply
    from pallas.product.llm.structured_reply import parse_structured_reply

    if reply_text and profile_for_task_type(task_type) is not None:
        reply_text, marker_intent = extract_sticker_marker(reply_text)

    had_reply_before_filter = bool(reply_text)
    direct_candidate = str(task.get("semantic_style_direct_candidate") or "").strip()
    structured_reply = StructuredChatReply.single(reply_text)
    if not (direct_candidate and reply_text == direct_candidate) and profile_for_task_type(task_type) is not None:
        structured_reply = parse_structured_reply(reply_text)
    structured_reply = resolve_output_filtered_chat_reply(task, structured_reply)
    reply_segments = list(structured_reply.reply_segments)
    band = str(task.get("reply_total_length_band") or "").strip()
    if len(reply_segments) == 1 and not (direct_candidate and reply_text == direct_candidate):
        from pallas.product.llm.reply_postprocess import (
            has_cjk_space_separator,
            split_short_reply_segments,
        )

        single_reply = reply_segments[0]
        if band == "short" and "\n" not in single_reply and not has_cjk_space_separator(single_reply):
            # 短档：模型单条短句即单泡，不再为了「短」而随机拆多泡
            reply_segments = [single_reply.strip()]
        elif "\n" in single_reply or has_cjk_space_separator(single_reply):
            reply_segments = split_short_reply_segments(
                single_reply,
                split_by_punctuation=False,
                max_segments=3,
            )
    reply_text = "\n".join(reply_segments)
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
        first_segment = strip_leading_self_at_mentions(
            reply_segments[0] if reply_segments else "",
            bot_self_id=bot_self_id,
            mention_names=mention_names,
        )
        reply_segments = [first_segment, *reply_segments[1:]] if first_segment else reply_segments[1:]
        reply_text = "\n".join(reply_segments)
    if task_type == LLM_CHAT_TASK_TYPE and not had_reply_before_filter:
        from pallas.product.llm.chat_empty_fallback import resolve_llm_chat_empty_fallback

        reply_text = resolve_llm_chat_empty_fallback(
            task,
            reply_text,
            suppress_empty_fallback=suppress_empty_fallback,
        )
        reply_segments = [reply_text] if reply_text else []
    learned_reply_text = "\n".join(reply_segments)
    delivery_segments = list(reply_segments)
    if delivery_segments:
        from pallas.product.llm.reply_postprocess import apply_reply_postprocess

        cfg = get_llm_config()
        delivery_segments = [
            processed
            for segment in delivery_segments
            if (
                processed := apply_reply_postprocess(
                    segment,
                    enabled=bool(cfg.llm_reply_postprocess_enabled),
                    typo_enabled=bool(cfg.llm_reply_typo_enabled),
                    typo_rate=float(cfg.llm_reply_typo_rate),
                    trim_terminal_period_enabled=bool(cfg.llm_reply_trim_terminal_period_enabled),
                    trim_terminal_period_rate=float(cfg.llm_reply_trim_terminal_period_rate),
                )
            )
        ]
        if delivery_segments and str(group_id or "").isdigit() and str(bot_id or "").isdigit():
            from pallas.product.llm.tools.social import is_social_request, replace_mention_tokens

            request_id = str(task.get("request_id") or task_id).strip()
            if is_social_request(int(bot_id), int(group_id), request_id):
                replaced = [
                    replace_mention_tokens(
                        segment,
                        bot_id=int(bot_id),
                        group_id=int(group_id),
                        request_id=request_id,
                    )
                    for segment in delivery_segments
                ]
                delivery_segments = [segment for segment in replaced if str(segment or "").strip()]
                if not delivery_segments:
                    log_rate_limited(
                        logger,
                        "info",
                        "llm.delivery.mention_token_silenced",
                        "AI callback reply silenced after unapproved mention token removal",
                    )
                reply_text = "\n".join(delivery_segments)
    sticker_intent = str(structured_reply.sticker_intent or "")
    if marker_intent and sticker_intent in ("", "none"):
        sticker_intent = marker_to_sticker_tokens(marker_intent)
    structured_sticker_requested = bool(
        delivery_segments
        and sticker_intent not in ("", "none")
        and group_id
        and bot is not None
        and bool(getattr(cfg, "llm_chat_sticker_enabled", False))
    )
    if delivery_segments and group_id and bot is not None:
        logger.info(
            f"Bot [{getattr(bot, 'self_id', bot_id_str or '<missing>')}] delivering a "
            f"[{task_type}] reply with ID [{task_id}] to group [{group_id}], length [{len(learned_reply_text)}]"
        )
        bubble_sleeper = sleeper or asyncio.sleep
        reply_to_message_id, at_user_id = resolve_llm_reply_delivery(
            task,
            group_id=group_id,
            mention_cooldown_sec=int(cfg.llm_reply_mention_cooldown_sec),
        )
        sent_indexes: list[int] = []
        from pallas.product.llm.sticker_followup import suppress_outgoing_sticker_followup

        for index, segment in enumerate(delivery_segments):
            if index:
                await sleep_between_bubbles(bubble_delay_seconds(delivery_segments[index - 1]), bubble_sleeper)
            from pallas.core.platform.ai_callback.delivery import send_group_message_with_receipt

            ownership = suppress_outgoing_sticker_followup() if structured_sticker_requested else nullcontext()
            with ownership:
                receipt = await send_group_message_with_receipt(
                    bot,
                    group_id,
                    segment,
                    reply_to_message_id=reply_to_message_id if index == 0 else None,
                    at_user_id=at_user_id if index == 0 else None,
                )
            if index == 0:
                bot_message_id = receipt.message_id
            ok = receipt.delivered
            if index == 0 and ok and at_user_id is not None:
                note_llm_reply_mention_sent(group_id)
            if not ok:
                logger.warning(
                    "AI callback bubble delivery stopped for task [{}], sent_indexes [{}], failed at index [{}]",
                    task_id,
                    sent_indexes,
                    index,
                )
                break
            from pallas.product.llm.bot_reply_context import record_bot_reply_context

            record_bot_reply_context(
                group_id=int(group_id),
                bot_id=int(bot_id),
                message_id=receipt.message_id,
                text=str(segment),
            )
            sent_indexes.append(index)
        text_delivered = len(sent_indexes) == len(delivery_segments)
        delivered = text_delivered and delivered
    if text_delivered and should_append_llm_session(task) and learned_reply_text:
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
        semantic_source_bound = semantic_source_matches_delivery(
            task,
            reply_segments=delivery_segments,
            bot_message_id=bot_message_id,
            text_delivered=text_delivered,
        )
        maybe_append_llm_repeater_feedback(
            task_id,
            task,
            learned_reply_text,
            bot_message_id=bot_message_id,
            semantic_source_bound=semantic_source_bound,
        )
    if text_delivered and structured_sticker_requested:
        from pallas.product.llm.sticker_followup import should_schedule_outgoing_sticker

        if should_schedule_outgoing_sticker(
            int(group_id),
            learned_reply_text,
            cooldown_sec=int(getattr(cfg, "llm_chat_sticker_cooldown_sec", 90)),
            max_per_hour=int(getattr(cfg, "llm_chat_sticker_max_per_hour", 8)),
        ):
            followup_task = asyncio.create_task(
                send_repeater_emotion_image(
                    bot,
                    int(group_id),
                    int(bot_id),
                    int(task.get("user_id") or 0),
                    sticker_intent,
                ),
                name=f"llm_sticker_followup:{task_id}",
            )
            followup_task.add_done_callback(_consume_sticker_label_enqueue_result)
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
                logger.debug("reply effect eval skipped for task [{}]", task_id)
    behavior_scene = str(task.get("behavior_scene") or "").strip()
    if text_delivered and task_type == LLM_CHAT_TASK_TYPE and behavior_scene:
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
                bubble_count=len(delivery_segments),
                bubble_rhythm="multi" if len(delivery_segments) > 1 else "single",
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
                auto_feedback_payload={
                    **({"agent_trace": parsed_agent_trace} if parsed_agent_trace else {}),
                    "bubble_count": len(delivery_segments),
                    "bubble_rhythm": "multi" if len(delivery_segments) > 1 else "single",
                },
            )
        )
    track_llm_callback(task, "callback_ok")
    if task_type == LLM_CHAT_TASK_TYPE and delivered and reply_text:
        logger.info(
            format_plugin_event(
                "deliver_reply",
                f"Bot [{bot_id}] delivered a reply in group [{group_id}], length [{len(reply_text)}]",
            )
        )
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
