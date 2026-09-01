"""受控的表情视觉标签后台任务。"""

from __future__ import annotations

import asyncio
import re
import time
from dataclasses import replace
from enum import StrEnum
from typing import Any

from nonebot import logger

from pallas.core.platform.work_jobs.models import WorkJob
from pallas.core.platform.work_jobs.runtime import build_work_job_store
from pallas.product.llm import sticker_label_runtime_state
from pallas.product.llm.sticker_labels import (
    ACTION_VOCABULARY,
    EMOTION_VOCABULARY,
    TONE_VOCABULARY,
    StickerSemanticLabel,
    content_hash_for_bytes,
    needs_relabel,
)

STICKER_LABEL_JOB_KIND = "sticker.label.visual"
STICKER_LABEL_PROMPT_VERSION = 1
STICKER_LABEL_MIN_CONFIDENCE = 0.6
STICKER_LABEL_TIMEOUT_SEC = 60.0
STICKER_LABEL_CIRCUIT_FAILURES = 3
STICKER_LABEL_CIRCUIT_COOLDOWN_SEC = 60.0
STICKER_LABEL_IMAGE_MAX_SIDE = 384
STICKER_LABEL_MAX_OUTPUT_TOKENS = 256
_STICKER_LABEL_SEMAPHORE = asyncio.Semaphore(1)
_REQUIRED_RESPONSE_FIELDS_MAX_ITEMS = 5


class StickerLabelSource(StrEnum):
    REPEATER_CANDIDATE = "repeater_candidate"
    FOLLOWUP_CANDIDATE = "followup_candidate"
    TEST_CANDIDATE = "test_candidate"
    RECOMMENDED_CANDIDATE = "recommended_candidate"
    MANUAL_STICKER = "manual_sticker"


class StickerLabelCacheChangedError(RuntimeError):
    """缓存键已指向不同图片，不能将标签写到错误哈希。"""


def sticker_label_circuit_open(*, now: float | None = None) -> bool:
    return sticker_label_runtime_state.sticker_label_circuit_open(now=now)


def sticker_label_circuit_record(success: bool, *, now: float | None = None) -> None:
    sticker_label_runtime_state.sticker_label_circuit_record(
        success,
        failure_threshold=STICKER_LABEL_CIRCUIT_FAILURES,
        cooldown_sec=STICKER_LABEL_CIRCUIT_COOLDOWN_SEC,
        now=now,
    )


def reset_sticker_label_runtime_state_for_tests() -> None:
    sticker_label_runtime_state.reset_sticker_label_runtime_state_for_tests()


def sticker_label_timeout_sec() -> float:
    from pallas.product.llm.config import get_llm_config

    value = getattr(get_llm_config(), "llm_sticker_label_timeout_sec", STICKER_LABEL_TIMEOUT_SEC)
    return max(1.0, float(value or STICKER_LABEL_TIMEOUT_SEC))


def lazy_sticker_labels_paused() -> bool:
    return sticker_label_runtime_state.lazy_sticker_labels_paused()


def set_lazy_sticker_labels_paused(paused: bool) -> bool:
    return sticker_label_runtime_state.set_lazy_sticker_labels_paused(paused)


def sticker_label_runtime_redis_key() -> str:
    return sticker_label_runtime_state.sticker_label_runtime_redis_key()


def sticker_label_realtime_budget_ok() -> bool:
    """实时标注每日预算闸：按当日已成功标注次数限制，避免无上限消耗。"""
    from pallas.product.llm.config import get_llm_config

    limit = max(0, int(getattr(get_llm_config(), "llm_sticker_label_realtime_daily_limit", 0) or 0))
    if limit <= 0:
        return True
    try:
        from pallas.product.llm.task_metrics import llm_task_metrics_snapshot

        snapshot = llm_task_metrics_snapshot()
        by_task = snapshot.get("by_task") if isinstance(snapshot.get("by_task"), dict) else {}
        row = by_task.get("sticker_label") if isinstance(by_task.get("sticker_label"), dict) else {}
        done = int(row.get("submit_ok") or 0)
    except Exception:
        return True
    return done < limit


def sticker_label_repository():
    from pallas.core.foundation.db import make_sticker_label_repository

    return make_sticker_label_repository()


def _parse_label_array_field(raw: object) -> tuple[str, ...]:
    """容忍数组或逗号分隔字符串；过滤空项并截断。"""
    if isinstance(raw, list):
        items = [str(item).strip() for item in raw if str(item).strip()]
    elif isinstance(raw, str):
        items = [item.strip() for item in re.split(r"[,，、;；]+", raw) if item.strip()]
    else:
        items = []
    return tuple(items)[:_REQUIRED_RESPONSE_FIELDS_MAX_ITEMS]


def parse_sticker_visual_label(raw: str) -> dict[str, object] | None:
    from pallas.product.llm.memory.graph.json_parse import parse_llm_json

    try:
        value = parse_llm_json(str(raw or ""))
    except ValueError:
        return None
    if not isinstance(value, dict):
        return None
    if not isinstance(value.get("is_sticker"), bool):
        return None
    confidence = value.get("confidence")
    if isinstance(confidence, bool) or not isinstance(confidence, (int, float)):
        return None
    intensity = value.get("intensity")
    if isinstance(intensity, bool) or not isinstance(intensity, int) or not 0 <= intensity <= 3:
        intensity = 0
    try:
        label = StickerSemanticLabel(
            content_hash="0" * 64,
            is_sticker=value["is_sticker"],
            emotions=_parse_label_array_field(value.get("emotions")),
            actions=_parse_label_array_field(value.get("actions")),
            tones=_parse_label_array_field(value.get("tones")),
            intensity=intensity,
            usage=_parse_label_array_field(value.get("usage")),
            avoid=_parse_label_array_field(value.get("avoid")),
            caption=str(value.get("caption") or "").strip(),
            confidence=confidence,
        )
    except Exception:
        return None
    return {
        "is_sticker": label.is_sticker,
        "emotions": label.emotions,
        "actions": label.actions,
        "tones": label.tones,
        "intensity": label.intensity,
        "usage": label.usage,
        "avoid": label.avoid,
        "caption": label.caption,
        "confidence": label.confidence,
    }


async def enqueue_sticker_label_candidate(*, cache_key: str, content: bytes, source: StickerLabelSource) -> bool:
    """仅为显式候选创建任务；普通缓存永不从这里扫描。"""
    if type(source) is not StickerLabelSource or not cache_key:
        return False
    if lazy_sticker_labels_paused():
        return False
    if not sticker_label_realtime_budget_ok():
        from pallas.product.llm.task_metrics import record_bot_llm_task

        record_bot_llm_task("sticker_label", "submit_skip")
        return False
    source_name = source.value
    if sticker_label_circuit_open():
        from pallas.product.llm.task_metrics import record_bot_llm_task

        record_bot_llm_task("sticker_label", "submit_skip")
        logger.info("sticker label enqueue skipped: circuit_open")
        return False
    content_hash = content_hash_for_bytes(content)
    existing = await sticker_label_repository().get(content_hash)
    if not needs_relabel(
        existing,
        prompt_version=STICKER_LABEL_PROMPT_VERSION,
        min_confidence=STICKER_LABEL_MIN_CONFIDENCE,
    ):
        from pallas.product.llm.task_metrics import record_bot_llm_task

        record_bot_llm_task("sticker_label", "cache_hit")
        return False
    from pallas.core.shared.utils.media_cache import bind_image_content_hash
    from pallas.product.llm.task_metrics import record_bot_llm_task

    await bind_image_content_hash(cache_key, content)
    job = WorkJob.create(
        kind=STICKER_LABEL_JOB_KIND,
        payload={},
        idempotency_key=f"{STICKER_LABEL_JOB_KIND}:{content_hash}:{STICKER_LABEL_PROMPT_VERSION}",
    )
    job = replace(
        job,
        payload={
            "content_hash": content_hash,
            "source": source_name,
            "prompt_version": STICKER_LABEL_PROMPT_VERSION,
            "observation": {"state": "queued"},
        },
    )
    _reactivated_job, reactivated = await build_work_job_store().requeue_terminal(job)
    record_bot_llm_task("sticker_label", "submit_ok" if reactivated else "background_coalesced")
    return True


async def label_sticker_with_vision(content: bytes) -> tuple[StickerSemanticLabel | None, str, str]:
    from pallas.product.llm.delivery import prepare_sticker_image
    from pallas.product.llm.provider_client import complete_chat_message
    from pallas.product.llm.providers_store import resolve_endpoint_for_task
    from pallas.product.llm.vision_messages import image_bytes_to_data_uri, openai_vision_user_content

    endpoint = resolve_endpoint_for_task("sticker_vision")
    if endpoint is None or "image" not in endpoint.capabilities:
        raise RuntimeError("no sticker vision endpoint")
    prepared = prepare_sticker_image(content, max_side=STICKER_LABEL_IMAGE_MAX_SIDE)
    data_uri = image_bytes_to_data_uri(prepared)
    if data_uri is None:
        raise ValueError("invalid sticker image")
    prompt = (
        "判断这张图片能否在群聊里当作表情/反应图使用。普通照片、聊天截图、游戏截图等"
        "只要画面传达明确情绪、适合接梗或回怼，都算适合；只有纯信息图、纯风景、无情绪指向的随手拍才算不适合。"
        "只输出严格 JSON 对象，不要任何前缀、解释或 markdown 围栏。"
        "字段必须且只能是 is_sticker, emotions, actions, tones, intensity, usage, avoid, caption, confidence。"
        f"emotions 只能从词表选 0-3 个：{','.join(EMOTION_VOCABULARY)}。"
        f"actions 只能从词表选 0-3 个：{','.join(ACTION_VOCABULARY)}。"
        f"tones 只能从词表选 0-3 个：{','.join(TONE_VOCABULARY)}。"
        "is_sticker 为布尔值；intensity 为 0-3 整数；usage/avoid 各 0-3 个字符串（每条≤12字）；"
        "caption 为一句话≤30字；confidence 为 0-1 数字。"
    )
    response = await asyncio.wait_for(
        complete_chat_message(
            [
                {"role": "system", "content": "你只输出 JSON，不加任何其他文字。"},
                {
                    "role": "user",
                    "content": openai_vision_user_content(
                        prompt,
                        [data_uri],
                    ),
                },
            ],
            model=endpoint.model,
            options={"temperature": 0.1, "max_tokens": STICKER_LABEL_MAX_OUTPUT_TOKENS},
            base_url=endpoint.base_url,
            api_key=endpoint.api_key,
            request_method=endpoint.request_method,
            task="sticker_label",
            provider_id=str(endpoint.provider_id or ""),
        ),
        timeout=sticker_label_timeout_sec(),
    )
    parsed = parse_sticker_visual_label(str(response.get("content") or ""))
    if parsed is None:
        raise ValueError("invalid sticker label JSON")
    return (
        StickerSemanticLabel(
            content_hash=content_hash_for_bytes(content),
            model=str(endpoint.model or ""),
            prompt_version=STICKER_LABEL_PROMPT_VERSION,
            **parsed,
        ),
        str(endpoint.provider_id or ""),
        str(endpoint.model or ""),
    )


async def save_sticker_label_observation(
    job_id: str,
    payload: dict[str, object],
    observation: dict[str, object],
) -> None:
    from pallas.core.foundation.db.runtime import is_postgresql_backend

    value = dict(payload)
    value["observation"] = observation
    if is_postgresql_backend():
        from sqlalchemy import update

        from pallas.core.foundation.db.repository_pg import BackgroundJobRow, get_session

        async with get_session() as session:
            await session.execute(update(BackgroundJobRow).where(BackgroundJobRow.id == job_id).values(payload=value))
            await session.commit()
        return
    from pallas.core.foundation.db.modules import BackgroundJob

    await BackgroundJob.get_pymongo_collection().update_one({"job_id": job_id}, {"$set": {"payload": value}})


def _is_content_rejection(exc: Exception) -> bool:
    if isinstance(exc, ValueError):
        return False
    text = str(exc or "").lower()
    return "data_inspection_failed" in text or "inappropriate content" in text


async def handle_sticker_label_visual(payload: dict[str, Any]) -> None:
    from pallas.core.shared.utils.media_cache import get_image_by_content_hash

    job_id = str(payload.get("job_id") or "").strip()
    expected_hash = str(payload.get("content_hash") or "").strip()
    observation = dict(payload.get("observation") or {})
    observation.update({"state": "running", "started_at": time.time()})
    if sticker_label_circuit_open():
        from pallas.product.llm.task_metrics import record_bot_llm_task

        record_bot_llm_task("sticker_label", "submit_skip")
        observation.update({"state": "circuit_open", "finished_at": time.time()})
        await save_sticker_label_observation(job_id, dict(payload), observation)
        return
    content = await get_image_by_content_hash(expected_hash)
    if not content or content_hash_for_bytes(content) != expected_hash:
        observation.update({"state": "cache_changed", "finished_at": time.time(), "error": "cache content changed"})
        await save_sticker_label_observation(job_id, dict(payload), observation)
        return
    try:
        timeout_sec = sticker_label_timeout_sec()
        deadline = asyncio.get_running_loop().time() + timeout_sec
        acquired = False
        try:
            await asyncio.wait_for(_STICKER_LABEL_SEMAPHORE.acquire(), timeout=timeout_sec)
            acquired = True
            remaining = max(0.0, deadline - asyncio.get_running_loop().time())
            label, provider, model = await asyncio.wait_for(label_sticker_with_vision(content), timeout=remaining)
        finally:
            if acquired:
                _STICKER_LABEL_SEMAPHORE.release()
        await sticker_label_repository().upsert(label)
        sticker_label_circuit_record(True)
        from pallas.product.llm.task_metrics import record_bot_llm_task

        record_bot_llm_task("sticker_label", "callback_ok")
    except Exception as exc:
        from pallas.product.llm.task_metrics import record_bot_llm_task

        failure_state = (
            "timeout"
            if isinstance(exc, TimeoutError)
            else "parse_error"
            if isinstance(exc, ValueError)
            else "no_vision"
            if "no sticker vision endpoint" in str(exc)
            else "failed"
        )
        if _is_content_rejection(exc):
            negative = StickerSemanticLabel(
                content_hash=expected_hash,
                is_sticker=False,
                confidence=0.9,
                prompt_version=STICKER_LABEL_PROMPT_VERSION,
            )
            await sticker_label_repository().upsert(negative)
            observation.update({
                "state": "rejected",
                "finished_at": time.time(),
                "is_sticker": False,
                "confidence": 0.9,
                "error": f"{type(exc).__name__}: {str(exc)[:200]}",
            })
            await save_sticker_label_observation(job_id, dict(payload), observation)
            logger.info("Sticker label content was rejected for job [{}]: [{}]", job_id, type(exc).__name__)
            return
        if failure_state not in {"parse_error", "no_vision"}:
            sticker_label_circuit_record(False)
            record_bot_llm_task("sticker_label", "callback_fail")
        observation.update({
            "state": failure_state,
            "finished_at": time.time(),
            "error": f"{type(exc).__name__}: {str(exc)[:200]}",
        })
        await save_sticker_label_observation(job_id, dict(payload), observation)
        logger.warning("Sticker label processing failed for job [{}]: [{}]", job_id, type(exc).__name__)
        if failure_state in {"parse_error", "no_vision"}:
            return
        raise
    observation.update({
        "state": "labeled",
        "finished_at": time.time(),
        "provider": provider,
        "model": model,
        "confidence": label.confidence,
        "is_sticker": label.is_sticker,
    })
    await save_sticker_label_observation(job_id, dict(payload), observation)
