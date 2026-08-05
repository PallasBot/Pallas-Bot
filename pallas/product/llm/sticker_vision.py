"""受控的 VLM 表情候选选择。"""

from __future__ import annotations

import asyncio
import json
import time
from collections import deque
from dataclasses import replace

from pallas.core.platform.work_jobs.models import WorkJob
from pallas.core.platform.work_jobs.runtime import build_work_job_store

_DISPATCH_TASK: asyncio.Task[None] | None = None
_VISION_SELECT_SEMAPHORE = asyncio.Semaphore(1)
_VISION_ENQUEUED_AT: deque[float] = deque()


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


async def choose_sticker_with_vision(
    candidates: list[tuple[str, bytes]],
    *,
    user_text: str,
    timeout_sec: float = 8.0,
) -> str | None:
    if len(candidates) < 3:
        return None
    from pallas.product.llm.provider_client import LlmProviderError, complete_chat_message
    from pallas.product.llm.providers_store import resolve_endpoint_for_task
    from pallas.product.llm.vision_messages import openai_vision_user_content

    endpoint = resolve_endpoint_for_task("sticker_vision")
    if endpoint is None or "image" not in endpoint.capabilities:
        return None
    import base64

    content = openai_vision_user_content(
        f"根据当前群聊选择最贴切的一张表情图。当前消息：{str(user_text or '')[:200]}。"
        '只输出 JSON：{"index":1}；不合适则 {"index":0}。',
        [f"data:image/jpeg;base64,{base64.b64encode(data).decode('ascii')}" for _key, data in candidates],
    )
    try:
        result = await asyncio.wait_for(
            complete_chat_message(
                [
                    {"role": "system", "content": "你是表情图选择器。只输出 JSON。"},
                    {"role": "user", "content": content},
                ],
                model=endpoint.model,
                options={"temperature": 0.1, "num_predict": 32},
                tools=None,
                base_url=endpoint.base_url,
                api_key=endpoint.api_key,
                request_method=endpoint.request_method,
                task="sticker_vision",
            ),
            timeout=max(1.0, float(timeout_sec)),
        )
    except (LlmProviderError, TimeoutError):
        return None
    index = parse_sticker_vision_choice(str(result.get("content") or ""), candidate_count=len(candidates))
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
) -> str:
    """将图片选择交由 work 辅进程执行，返回可轮询的 job id。"""
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
        },
    }
    job = replace(job, payload=payload)
    return (await build_work_job_store().enqueue(job)).id


async def handle_sticker_vision_select(payload: dict[str, object]) -> None:
    """work 进程从图片缓存加载候选，并把选择结果写回任务 payload。"""
    from pallas.core.shared.utils.media_cache import get_image

    job_id = str(payload.get("job_id") or "").strip()
    candidate_codes = [str(item) for item in list(payload.get("candidate_cq_codes") or []) if str(item).strip()]
    candidates = [(cq_code, image) for cq_code in candidate_codes if (image := await get_image(cq_code))]
    async with _VISION_SELECT_SEMAPHORE:
        selected = await choose_sticker_with_vision(
            candidates,
            user_text=str(payload.get("user_text") or ""),
            timeout_sec=float(payload.get("timeout_sec") or 8.0),
        )
    await save_sticker_vision_result(job_id, dict(payload), selected)


async def save_sticker_vision_result(job_id: str, payload: dict[str, object], selected_cq_code: str | None) -> None:
    """将 work 结果和任务本身放在同一条持久化记录中，避免额外结果表。"""
    from pallas.core.foundation.db.runtime import is_postgresql_backend

    value = dict(payload)
    value["vision_result"] = {"selected_cq_code": selected_cq_code}
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
    if bot is None or not raw_image:
        return True
    from pallas.core.shared.utils.media_cache import get_image

    message = Message()
    for segment in Message(raw_image):
        if segment.type != "image":
            message += segment
            continue
        cached = await get_image(str(segment))
        if not cached:
            return True
        message += MessageSegment.image(file=cached)
    try:
        await bot.call_api("send_group_msg", group_id=int(delivery.get("group_id") or 0), message=message)
    except Exception:
        return True
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
