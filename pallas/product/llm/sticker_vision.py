"""受控的 VLM 表情候选选择。"""

from __future__ import annotations

import asyncio
import json
import time
from collections import deque
from dataclasses import replace

from nonebot import logger

from pallas.core.foundation.logging.bridge import format_business_event
from pallas.core.platform.work_jobs.models import WorkJob
from pallas.core.platform.work_jobs.runtime import build_work_job_store
from pallas.product.llm.inference_params import task_token_budget

_DISPATCH_TASK: asyncio.Task[None] | None = None
_VISION_SELECT_SEMAPHORE = asyncio.Semaphore(1)
_VISION_ENQUEUED_AT: deque[float] = deque()
VISION_CANDIDATE_MAX_SIDE = 384


def allow_sticker_vision_enqueue(max_per_hour: int, *, now: float | None = None) -> bool:
    current = time.monotonic() if now is None else float(now)
    while _VISION_ENQUEUED_AT and current - _VISION_ENQUEUED_AT[0] >= 3600:
        _VISION_ENQUEUED_AT.popleft()
    if max(0, int(max_per_hour)) <= len(_VISION_ENQUEUED_AT):
        return False
    _VISION_ENQUEUED_AT.append(current)
    return True


def parse_sticker_vision_choice(raw: str, *, candidate_count: int) -> int | None:
    try:
        payload = json.loads(str(raw or ""))
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, dict):
        return None
    index = payload.get("index")
    if isinstance(index, bool) or not isinstance(index, int) or not 1 <= index <= int(candidate_count):
        return None
    return index - 1


def prepare_sticker_vision_candidates(candidates: list[tuple[str, bytes]]) -> list[tuple[str, bytes]]:
    from pallas.product.llm.delivery import prepare_sticker_image

    return [
        (cq_code, prepare_sticker_image(image, max_side=VISION_CANDIDATE_MAX_SIDE)) for cq_code, image in candidates
    ]


def build_sticker_vision_stats(records: list[dict[str, object]], *, recent_limit: int = 8) -> dict[str, object]:
    """将 durable job 里的表情视觉状态聚合为控制台可读数据。"""
    requests = selected = failed = skipped = no_match = sent = delivery_failed = candidate_total = 0
    durations: list[int] = []
    latest_error = ""
    recent: list[dict[str, object]] = []
    ordered = sorted(records, key=lambda row: float(row.get("created_at") or 0), reverse=True)
    for row in ordered:
        payload = row.get("payload") if isinstance(row.get("payload"), dict) else {}
        observation = payload.get("vision_observation") if isinstance(payload.get("vision_observation"), dict) else {}
        delivery = payload.get("delivery") if isinstance(payload.get("delivery"), dict) else {}
        state = str(observation.get("state") or "queued")
        if state != "queued":
            requests += 1
        if state == "selected":
            selected += 1
        elif state == "failed":
            failed += 1
        elif state == "skipped":
            skipped += 1
        elif state == "no_match":
            no_match += 1
        if str(delivery.get("state") or "") == "sent":
            sent += 1
        elif str(delivery.get("state") or "") == "failed":
            delivery_failed += 1
        candidate_total += max(0, int(observation.get("candidate_count") or 0))
        duration = max(0, int(observation.get("duration_ms") or 0))
        if duration:
            durations.append(duration)
        error = str(observation.get("error") or delivery.get("error") or "").strip()[:240]
        if error and not latest_error:
            latest_error = error
        if len(recent) < max(1, int(recent_limit)):
            recent.append({
                "job_id": str(row.get("job_id") or "")[:64],
                "created_at": float(row.get("created_at") or 0),
                "state": state,
                "candidate_count": max(0, int(observation.get("candidate_count") or 0)),
                "provider": str(observation.get("provider") or ""),
                "model": str(observation.get("model") or ""),
                "duration_ms": duration or None,
                "delivery_state": str(delivery.get("state") or "pending"),
                "error": error or None,
            })
    return {
        "requests": requests,
        "selected": selected,
        "failed": failed,
        "skipped": skipped,
        "no_match": no_match,
        "sent": sent,
        "delivery_failed": delivery_failed,
        "candidate_total": candidate_total,
        "avg_duration_ms": round(sum(durations) / len(durations)) if durations else None,
        "recent_error": latest_error or None,
        "recent": recent,
    }


async def fetch_sticker_vision_stats(*, recent_limit: int = 8, aggregate_limit: int = 500) -> dict[str, object]:
    """读取当日 VLM 表情任务，work aux 与主进程共享同一 durable store。"""
    from datetime import datetime

    from pallas.core.foundation.db.runtime import is_postgresql_backend

    day_start = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
    records: list[dict[str, object]] = []
    if is_postgresql_backend():
        from sqlalchemy import select

        from pallas.core.foundation.db.repository_pg import BackgroundJobRow, get_session

        async with get_session(read_only=True) as session:
            rows = (
                await session.execute(
                    select(BackgroundJobRow.id, BackgroundJobRow.created_at, BackgroundJobRow.payload)
                    .where(BackgroundJobRow.kind == "sticker_vision.select", BackgroundJobRow.created_at >= day_start)
                    .order_by(BackgroundJobRow.created_at.desc())
                    .limit(max(1, int(aggregate_limit)))
                )
            ).all()
        records = [
            {"job_id": str(row.id), "created_at": float(row.created_at or 0), "payload": dict(row.payload or {})}
            for row in rows
        ]
    else:
        from pallas.core.foundation.db.modules import BackgroundJob

        cursor = (
            BackgroundJob
            .get_pymongo_collection()
            .find({"kind": "sticker_vision.select", "created_at": {"$gte": day_start}})
            .sort("created_at", -1)
            .limit(max(1, int(aggregate_limit)))
        )
        rows = await cursor.to_list(length=max(1, int(aggregate_limit)))
        records = [
            {
                "job_id": str(row.get("job_id") or ""),
                "created_at": float(row.get("created_at") or 0),
                "payload": dict(row.get("payload") or {}),
            }
            for row in rows
        ]
    return build_sticker_vision_stats(records, recent_limit=recent_limit)


async def choose_sticker_with_vision(
    candidates: list[tuple[str, bytes]],
    *,
    user_text: str,
    timeout_sec: float = 8.0,
    observation: dict[str, object] | None = None,
) -> str | None:
    details = observation if observation is not None else {}
    details["candidate_count"] = len(candidates)
    if len(candidates) < 3:
        details["state"] = "skipped"
        details["error"] = "候选表情不足 3 张"
        return None
    from pallas.product.llm.provider_client import LlmProviderError, complete_chat_message
    from pallas.product.llm.providers_store import resolve_endpoint_for_task
    from pallas.product.llm.vision_messages import openai_vision_user_content

    endpoint = resolve_endpoint_for_task("sticker_vision")
    if endpoint is None or "image" not in endpoint.capabilities:
        details["state"] = "skipped"
        details["error"] = "未配置支持图片的表情视觉模型"
        return None
    import base64

    from pallas.product.llm.task_metrics import record_bot_llm_task

    provider = str(getattr(endpoint, "provider_id", "") or "")
    details["provider"] = provider
    details["model"] = str(endpoint.model or "")
    details["started_at"] = time.time()
    started = time.monotonic()

    content = openai_vision_user_content(
        f"根据当前群聊选择最贴切的一张表情图。当前消息：{str(user_text or '')[:200]}。"
        '只输出 JSON：{"index":1}；不合适则 {"index":0}。',
        [f"data:image/jpeg;base64,{base64.b64encode(data).decode('ascii')}" for _key, data in candidates],
    )
    try:
        record_bot_llm_task("sticker_vision", "submit_ok")
        result = await asyncio.wait_for(
            complete_chat_message(
                [
                    {"role": "system", "content": "你是表情图选择器。只输出 JSON。"},
                    {"role": "user", "content": content},
                ],
                model=endpoint.model,
                options={
                    "temperature": 0.1,
                    "num_predict": task_token_budget("sticker_vision"),
                },
                tools=None,
                base_url=endpoint.base_url,
                api_key=endpoint.api_key,
                request_method=endpoint.request_method,
                task="sticker_vision",
                provider_id=provider,
            ),
            timeout=max(1.0, float(timeout_sec)),
        )
    except (LlmProviderError, TimeoutError) as exc:
        details["state"] = "failed"
        details["duration_ms"] = int((time.monotonic() - started) * 1000)
        details["finished_at"] = time.time()
        details["error"] = f"{type(exc).__name__}: {str(exc)[:200]}"
        logger.warning(
            format_business_event(
                "贴纸视觉选择",
                "失败",
                job_id=details.get("job_id"),
                provider=provider,
                model=endpoint.model,
                candidates=len(candidates),
                duration_ms=details["duration_ms"],
                error=type(exc).__name__,
            )
        )
        record_bot_llm_task("sticker_vision", "callback_fail")
        return None
    record_bot_llm_task("sticker_vision", "callback_ok")
    index = parse_sticker_vision_choice(str(result.get("content") or ""), candidate_count=len(candidates))
    details["duration_ms"] = int((time.monotonic() - started) * 1000)
    details["finished_at"] = time.time()
    details["state"] = "selected" if index is not None else "no_match"
    logger.info(
        format_business_event(
            "贴纸视觉选择",
            "已完成",
            job_id=details.get("job_id"),
            provider=provider,
            model=endpoint.model,
            candidates=len(candidates),
            state=details["state"],
            duration_ms=details["duration_ms"],
        )
    )
    return candidates[index][0] if index is not None else None


async def enqueue_sticker_vision_job(
    candidates: list[tuple[str, bytes]],
    *,
    user_text: str,
    timeout_sec: float,
    idempotency_key: str,
    bot_id: int,
    group_id: int,
    fallback_cq_code: str,
    cooldown_sec: int = 90,
) -> str:
    """将图片选择交由 work 辅进程执行，返回可轮询的 job id。"""
    from pallas.product.llm.sticker_label_jobs import StickerLabelSource, enqueue_sticker_label_candidate

    source = (
        StickerLabelSource.TEST_CANDIDATE
        if idempotency_key.startswith("sticker_vision.test:")
        else StickerLabelSource.FOLLOWUP_CANDIDATE
    )
    for cache_key, content in candidates:
        try:
            await enqueue_sticker_label_candidate(cache_key=cache_key, content=content, source=source)
        except Exception as exc:
            logger.debug("sticker label enqueue skipped: {}", exc)
    job = WorkJob.create(
        kind="sticker_vision.select",
        payload={},
        idempotency_key=idempotency_key,
    )
    payload = {
        "job_id": job.id,
        "candidate_cq_codes": [cq_code for cq_code, _data in candidates],
        "user_text": str(user_text or "")[:200],
        "timeout_sec": float(timeout_sec),
        "delivery": {
            "state": "pending",
            "bot_id": int(bot_id),
            "group_id": int(group_id),
            "fallback_cq_code": str(fallback_cq_code),
            "cooldown_sec": max(0, int(cooldown_sec)),
        },
        "vision_observation": {
            "job_id": job.id,
            "state": "queued",
            "enqueued_at": time.time(),
            "candidate_count": len(candidates),
        },
    }
    logger.debug(
        format_business_event(
            "贴纸视觉选择", "已入队", job_id=job.id, candidates=len(candidates), bot=bot_id, group=group_id
        )
    )
    job = replace(job, payload=payload)
    return (await build_work_job_store().enqueue(job)).id


async def handle_sticker_vision_select(payload: dict[str, object]) -> None:
    """work 进程从图片缓存加载候选，并把选择结果写回任务 payload。"""
    from pallas.core.shared.utils.media_cache import get_image

    job_id = str(payload.get("job_id") or "").strip()
    candidate_codes = [str(item) for item in list(payload.get("candidate_cq_codes") or []) if str(item).strip()]
    candidates = [(cq_code, image) for cq_code in candidate_codes if (image := await get_image(cq_code))]
    candidates = prepare_sticker_vision_candidates(candidates)
    observation = dict(payload.get("vision_observation") or {})
    observation.update({
        "job_id": job_id,
        "state": "running",
        "started_at": time.time(),
        "candidate_count": len(candidates),
    })
    try:
        async with _VISION_SELECT_SEMAPHORE:
            selected = await choose_sticker_with_vision(
                candidates,
                user_text=str(payload.get("user_text") or ""),
                timeout_sec=float(payload.get("timeout_sec") or 8.0),
                observation=observation,
            )
    except Exception as exc:
        observation.update({
            "state": "failed",
            "finished_at": time.time(),
            "error": f"{type(exc).__name__}: {str(exc)[:200]}",
        })
        await save_sticker_vision_result(job_id, dict(payload), None, observation=observation)
        raise
    await save_sticker_vision_result(job_id, dict(payload), selected, observation=observation)


async def save_sticker_vision_result(
    job_id: str,
    payload: dict[str, object],
    selected_cq_code: str | None,
    *,
    observation: dict[str, object] | None = None,
) -> None:
    """将 work 结果和任务本身放在同一条持久化记录中，避免额外结果表。"""
    from pallas.core.foundation.db.runtime import is_postgresql_backend

    value = dict(payload)
    value["vision_result"] = {"selected_cq_code": selected_cq_code}
    if observation is not None:
        value["vision_observation"] = dict(observation)
    if is_postgresql_backend():
        from sqlalchemy import update

        from pallas.core.foundation.db.repository_pg import BackgroundJobRow, get_session

        async with get_session() as session:
            await session.execute(update(BackgroundJobRow).where(BackgroundJobRow.id == job_id).values(payload=value))
            await session.commit()
        return
    from pallas.core.foundation.db.modules import BackgroundJob

    await BackgroundJob.get_pymongo_collection().update_one({"job_id": job_id}, {"$set": {"payload": value}})


async def save_sticker_vision_delivery(
    job_id: str,
    payload: dict[str, object],
    *,
    state: str,
    error: str = "",
) -> None:
    """记录主进程实际发图结果，领取后不让任务停留在模糊的 sending。"""
    delivery = payload.get("delivery") if isinstance(payload.get("delivery"), dict) else {}
    value = dict(payload)
    value["delivery"] = {**delivery, "state": state, "finished_at": time.time(), "error": error[:240] or None}
    from pallas.core.foundation.db.runtime import is_postgresql_backend

    if is_postgresql_backend():
        from sqlalchemy import update

        from pallas.core.foundation.db.repository_pg import BackgroundJobRow, get_session

        async with get_session() as session:
            await session.execute(update(BackgroundJobRow).where(BackgroundJobRow.id == job_id).values(payload=value))
            await session.commit()
        return
    from pallas.core.foundation.db.modules import BackgroundJob

    await BackgroundJob.get_pymongo_collection().update_one({"job_id": job_id}, {"$set": {"payload": value}})


async def read_sticker_vision_result(job_id: str) -> tuple[bool, str | None]:
    """返回 ``(ready, selected_cq_code)``；未完成与失败回退均由调用方处理。"""
    from pallas.core.foundation.db.runtime import is_postgresql_backend

    if is_postgresql_backend():
        from sqlalchemy import select

        from pallas.core.foundation.db.repository_pg import BackgroundJobRow, get_session

        async with get_session(read_only=True) as session:
            statement = select(BackgroundJobRow.payload).where(BackgroundJobRow.id == job_id)
            row = (await session.execute(statement)).scalar_one_or_none()
        payload = dict(row or {})
    else:
        from pallas.core.foundation.db.modules import BackgroundJob

        row = await BackgroundJob.find_one(BackgroundJob.job_id == job_id)
        payload = dict(row.payload or {}) if row else {}
    result = payload.get("vision_result")
    if not isinstance(result, dict) or "selected_cq_code" not in result:
        return False, None
    selected = result.get("selected_cq_code")
    return True, str(selected) if selected else None


async def claim_sticker_vision_delivery(bot_ids: set[int]) -> dict[str, object] | None:
    """原子领取一条已完成的选图派发记录，避免多主进程重复发送。"""
    if not bot_ids:
        return None
    from pallas.core.foundation.db.runtime import is_postgresql_backend

    if is_postgresql_backend():
        from sqlalchemy import select

        from pallas.core.foundation.db.repository_pg import BackgroundJobRow, get_session

        async with get_session() as session:
            rows = (
                await session.execute(
                    select(BackgroundJobRow)
                    .where(BackgroundJobRow.kind == "sticker_vision.select", BackgroundJobRow.status == "done")
                    .order_by(BackgroundJobRow.finished_at)
                    .limit(32)
                    .with_for_update(skip_locked=True)
                )
            ).scalars()
            for row in rows:
                payload = dict(row.payload or {})
                delivery = payload.get("delivery")
                if not isinstance(delivery, dict) or delivery.get("state") != "pending":
                    continue
                if int(delivery.get("bot_id") or 0) not in bot_ids:
                    continue
                payload["delivery"] = {**delivery, "state": "sending", "claimed_at": time.time()}
                row.payload = payload
                await session.commit()
                return payload
        return None

    from pallas.core.foundation.db.modules import BackgroundJob

    collection = BackgroundJob.get_pymongo_collection()
    row = await collection.find_one_and_update(
        {
            "kind": "sticker_vision.select",
            "status": "done",
            "payload.delivery.state": "pending",
            "payload.delivery.bot_id": {"$in": sorted(bot_ids)},
        },
        {"$set": {"payload.delivery.state": "sending", "payload.delivery.claimed_at": time.time()}},
        return_document=True,
    )
    return dict(row.get("payload") or {}) if row else None


async def dispatch_sticker_vision_delivery_once() -> bool:
    from nonebot import get_bots
    from nonebot.adapters.onebot.v11 import Message, MessageSegment

    payload = await claim_sticker_vision_delivery({int(key) for key in get_bots() if str(key).isdigit()})
    if payload is None:
        return False
    delivery = payload.get("delivery") if isinstance(payload.get("delivery"), dict) else {}
    bot = get_bots().get(str(int(delivery.get("bot_id") or 0)))
    result = payload.get("vision_result") if isinstance(payload.get("vision_result"), dict) else {}
    raw_image = str(result.get("selected_cq_code") or delivery.get("fallback_cq_code") or "")
    job_id = str(payload.get("job_id") or "")
    if bot is None or not raw_image:
        await save_sticker_vision_delivery(job_id, payload, state="failed", error="发送目标或图片不可用")
        return True
    from pallas.core.shared.utils.media_cache import get_image
    from pallas.product.llm.delivery import prepare_sticker_image
    from pallas.product.llm.sticker_followup import note_repeater_image_sent, should_send_repeater_image
    from pallas.product.llm.sticker_labels import content_hash_for_bytes

    message = Message()
    content_hash = ""
    for segment in Message(raw_image):
        if segment.type != "image":
            message += segment
            continue
        cached = await get_image(str(segment))
        if not cached:
            await save_sticker_vision_delivery(job_id, payload, state="failed", error="图片缓存已失效")
            return True
        content_hash = content_hash_for_bytes(cached)
        if not should_send_repeater_image(
            int(delivery.get("group_id") or 0),
            raw_image,
            cooldown_sec=int(delivery.get("cooldown_sec") or 0),
        ):
            await save_sticker_vision_delivery(job_id, payload, state="failed", error="表情图发送条件已失效")
            return True
        message += MessageSegment.image(file=prepare_sticker_image(cached))
    try:
        await bot.call_api("send_group_msg", group_id=int(delivery.get("group_id") or 0), message=message)
    except Exception as exc:
        await save_sticker_vision_delivery(job_id, payload, state="failed", error=f"{type(exc).__name__}: {exc}")
        logger.warning(format_business_event("贴纸视觉投递", "失败", job_id=job_id, error=type(exc).__name__))
        return True
    await save_sticker_vision_delivery(job_id, payload, state="sent")
    note_repeater_image_sent(int(delivery.get("group_id") or 0), raw_image, content_hash=content_hash)
    logger.info(format_business_event("贴纸视觉投递", "已完成", job_id=job_id, group=delivery.get("group_id")))
    return True


async def run_sticker_vision_delivery_dispatcher() -> None:
    while True:
        if not await dispatch_sticker_vision_delivery_once():
            await asyncio.sleep(0.5)


def bind_sticker_vision_delivery_dispatcher() -> None:
    from nonebot import get_driver

    driver = get_driver()

    @driver.on_startup
    async def _on_startup() -> None:
        global _DISPATCH_TASK
        if _DISPATCH_TASK is None or _DISPATCH_TASK.done():
            _DISPATCH_TASK = asyncio.create_task(run_sticker_vision_delivery_dispatcher())

    @driver.on_shutdown
    async def _on_shutdown() -> None:
        global _DISPATCH_TASK
        if _DISPATCH_TASK is not None:
            _DISPATCH_TASK.cancel()
            await asyncio.gather(_DISPATCH_TASK, return_exceptions=True)
            _DISPATCH_TASK = None
