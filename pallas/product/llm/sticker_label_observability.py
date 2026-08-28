"""表情标签观测与维护；只基于标签表和已入队任务。"""

from __future__ import annotations

import asyncio
import time

from nonebot import logger

from pallas.core.platform.shard.coord.coord_redis_store import coord_key, mutate_json_sync, read_json_sync
from pallas.core.platform.work_jobs.models import WorkJob
from pallas.core.platform.work_jobs.runtime import build_work_job_store
from pallas.product.llm.sticker_label_jobs import (
    STICKER_LABEL_JOB_KIND,
    STICKER_LABEL_MIN_CONFIDENCE,
    STICKER_LABEL_PROMPT_VERSION,
    lazy_sticker_labels_paused,
    set_lazy_sticker_labels_paused,  # noqa: F401
)
from pallas.product.llm.sticker_label_runtime_state import snapshot as sticker_label_runtime_snapshot

_STICKER_BACKFILL_KEY = coord_key("llm", "sticker-label-backfill")
_STICKER_BACKFILL_TTL_SEC = 2 * 86400
_STICKER_BACKFILL_INTERVAL_SEC = 30 * 60
_STICKER_BACKFILL_BATCH_SIZE = 64
_STICKER_BACKFILL_LIFECYCLE_BOUND = False


def sticker_label_backfill_used_today() -> int:
    state = read_json_sync(_STICKER_BACKFILL_KEY)
    if not isinstance(state, dict):
        return 0
    from datetime import date

    if str(state.get("day") or "") != str(date.today()):
        return 0
    return max(0, int(state.get("used") or 0))


def _backfill_ttl(_state: dict) -> int:
    return _STICKER_BACKFILL_TTL_SEC


def sticker_label_backfill_account(amount: int) -> int:
    """原子记录当日已用回填条数，返回更新后的累计值。"""
    from datetime import date

    today = str(date.today())

    def update(state: dict) -> None:
        if str(state.get("day") or "") != today:
            state.clear()
            state["day"] = today
            state["used"] = 0
        state["used"] = max(0, int(state.get("used") or 0)) + max(0, int(amount))

    shared = mutate_json_sync(_STICKER_BACKFILL_KEY, update, ttl_sec_fn=_backfill_ttl)
    if shared is None:
        return sticker_label_backfill_used_today()
    return max(0, int(shared.get("used") or 0))


def build_sticker_label_job_stats(records: list[dict[str, object]], *, recent_limit: int = 8) -> dict[str, object]:
    submitted = labeled = pending = failed = 0
    timeout = parse_error = no_vision = circuit_open = cache_changed = 0
    recent_errors: list[dict[str, object]] = []
    for row in sorted(records, key=lambda item: float(item.get("created_at") or 0), reverse=True):
        submitted += 1
        payload = row.get("payload") if isinstance(row.get("payload"), dict) else {}
        observation = payload.get("observation") if isinstance(payload.get("observation"), dict) else {}
        state = str(observation.get("state") or "queued")
        if state in {"queued", "running"}:
            pending += 1
        elif state == "labeled":
            labeled += 1
        elif state == "timeout":
            timeout += 1
        elif state == "parse_error":
            parse_error += 1
        elif state == "no_vision":
            no_vision += 1
        elif state == "circuit_open":
            circuit_open += 1
        elif state == "cache_changed":
            cache_changed += 1
        elif state == "failed":
            failed += 1
        error = str(observation.get("error") or row.get("last_error") or "").strip()
        if error:
            if len(recent_errors) < max(1, int(recent_limit)):
                recent_errors.append({
                    "job_id": str(row.get("job_id") or "")[:64],
                    "created_at": float(row.get("created_at") or 0),
                    "state": state,
                    "error": error[:240],
                })
    return {
        "submitted": submitted,
        "labeled": labeled,
        "pending": pending,
        "failed": failed,
        "timeout": timeout,
        "parse_error": parse_error,
        "no_vision": no_vision,
        "circuit_open": circuit_open,
        "cache_changed": cache_changed,
        "recent_errors": recent_errors,
    }


async def fetch_sticker_label_job_stats(*, recent_limit: int = 8, aggregate_limit: int = 500) -> dict[str, object]:
    from pallas.core.foundation.db.runtime import is_postgresql_backend

    if is_postgresql_backend():
        from sqlalchemy import select

        from pallas.core.foundation.db.repository_pg import BackgroundJobRow, get_session

        async with get_session(read_only=True) as session:
            rows = (
                await session.execute(
                    select(
                        BackgroundJobRow.id,
                        BackgroundJobRow.created_at,
                        BackgroundJobRow.payload,
                        BackgroundJobRow.last_error,
                    )
                    .where(BackgroundJobRow.kind == STICKER_LABEL_JOB_KIND)
                    .order_by(BackgroundJobRow.created_at.desc())
                    .limit(max(1, int(aggregate_limit)))
                )
            ).all()
        records = [
            {
                "job_id": str(row.id),
                "created_at": float(row.created_at or 0),
                "payload": dict(row.payload or {}),
                "last_error": row.last_error,
            }
            for row in rows
        ]
    else:
        from pallas.core.foundation.db.modules import BackgroundJob

        rows = await (
            BackgroundJob
            .get_pymongo_collection()
            .find({"kind": STICKER_LABEL_JOB_KIND}, {"job_id": 1, "created_at": 1, "payload": 1, "last_error": 1})
            .sort("created_at", -1)
            .limit(max(1, int(aggregate_limit)))
            .to_list(length=max(1, int(aggregate_limit)))
        )
        records = [
            {
                "job_id": str(row.get("job_id") or ""),
                "created_at": float(row.get("created_at") or 0),
                "payload": dict(row.get("payload") or {}),
                "last_error": row.get("last_error"),
            }
            for row in rows
        ]
    return build_sticker_label_job_stats(records, recent_limit=recent_limit)


async def build_sticker_label_overview() -> dict[str, object]:
    from pallas.core.foundation.db import make_sticker_label_repository
    from pallas.product.llm.sticker_vision import fetch_sticker_vision_stats

    labels, jobs, vision = await asyncio.gather(
        make_sticker_label_repository().stats(
            min_confidence=STICKER_LABEL_MIN_CONFIDENCE,
            current_prompt_version=STICKER_LABEL_PROMPT_VERSION,
        ),
        fetch_sticker_label_job_stats(),
        fetch_sticker_vision_stats(),
    )
    return {
        "labels": labels,
        "jobs": jobs,
        "lazy_labels_paused": lazy_sticker_labels_paused(),
        "label_circuit_open": float(sticker_label_runtime_snapshot()["circuit_until"]) > time.time(),
        "vlm_refine_avoided": int(vision.get("skipped") or 0) + int(vision.get("no_match") or 0),
        "vlm_refine_actual": int(vision.get("requests") or 0),
        "send_hits": int(vision.get("sent") or 0),
    }


async def requeue_stale_sticker_labels(
    *,
    limit: int = 200,
    label_repository=None,
    image_cache_repository=None,
    work_job_store=None,
) -> dict[str, int]:
    from pallas.core.foundation.db import make_image_cache_repository, make_sticker_label_repository

    labels_repo = label_repository or make_sticker_label_repository()
    image_repo = image_cache_repository or make_image_cache_repository()
    jobs = work_job_store or build_work_job_store()
    labels = await labels_repo.list_relabel_candidates(
        min_confidence=STICKER_LABEL_MIN_CONFIDENCE,
        current_prompt_version=STICKER_LABEL_PROMPT_VERSION,
        limit=limit,
    )
    queued = skipped = missing_cache = 0
    for label in labels:
        cache = await image_repo.find_by_content_hash(label.content_hash)
        blob = bytes(cache.blob_data) if cache and cache.blob_data else b""
        from pallas.product.llm.sticker_labels import content_hash_for_bytes

        if not blob:
            missing_cache += 1
            continue
        if content_hash_for_bytes(blob) != label.content_hash:
            skipped += 1
            continue
        job = WorkJob.create(
            kind=STICKER_LABEL_JOB_KIND,
            payload={
                "content_hash": label.content_hash,
                "source": "manual_requeue",
                "prompt_version": STICKER_LABEL_PROMPT_VERSION,
                "observation": {"state": "queued"},
            },
            idempotency_key=f"{STICKER_LABEL_JOB_KIND}:{label.content_hash}:{STICKER_LABEL_PROMPT_VERSION}",
        )
        _, reactivated = await jobs.requeue_terminal(job)
        if reactivated:
            queued += 1
        else:
            skipped += 1
    return {"requeued": queued, "queued": queued, "skipped": skipped, "missing_cache": missing_cache}


async def clear_sticker_label(content_hash: str) -> bool:
    from pallas.core.foundation.db import make_sticker_label_repository

    return await make_sticker_label_repository().delete(content_hash)


async def list_unlabeled_content_hashes(*, limit: int = 64) -> list[str]:
    """从图片缓存中挑选尚无标签、且 blob 可用的 content_hash（按最新优先）。"""
    from pallas.core.foundation.db.runtime import is_postgresql_backend

    if is_postgresql_backend():
        from sqlalchemy import select

        from pallas.core.foundation.db.repository_pg import (
            ImageCacheRow,
            StickerLabelRow,
            get_session,
            image_cache_has_blob_clause,
        )

        async with get_session(read_only=True) as session:
            rows = (
                await session.execute(
                    select(ImageCacheRow.content_hash)
                    .where(
                        ImageCacheRow.content_hash.is_not(None),
                        image_cache_has_blob_clause(),
                        ~ImageCacheRow.content_hash.in_(
                            select(StickerLabelRow.content_hash).where(StickerLabelRow.content_hash.is_not(None))
                        ),
                    )
                    .order_by(ImageCacheRow.date.desc(), ImageCacheRow.id.desc())
                    .limit(max(1, int(limit)))
                )
            ).all()
        return [str(row[0]) for row in rows if row[0]]
    return []


async def backfill_sticker_labels_batch(
    *,
    daily_limit: int,
    batch_limit: int = _STICKER_BACKFILL_BATCH_SIZE,
    label_repository=None,
    image_cache_repository=None,
    work_job_store=None,
) -> dict[str, int]:
    """在每日预算内为缺失标签的图入队标签任务。"""
    from pallas.core.foundation.db import make_image_cache_repository
    from pallas.product.llm.sticker_label_jobs import StickerLabelSource

    used = sticker_label_backfill_used_today()
    remaining = max(0, int(daily_limit) - used)
    if remaining <= 0:
        return {"queued": 0, "skipped": 0, "missing_cache": 0, "budget_exhausted": True, "used": used}

    image_repo = image_cache_repository or make_image_cache_repository()
    image_repo = image_cache_repository or make_image_cache_repository()
    jobs = work_job_store or build_work_job_store()
    content_hashes = await list_unlabeled_content_hashes(limit=min(int(batch_limit), remaining))
    queued = skipped = missing_cache = 0
    for content_hash in content_hashes:
        cache = await image_repo.find_by_content_hash(content_hash)
        blob = bytes(cache.blob_data) if cache and cache.blob_data else b""
        from pallas.product.llm.sticker_labels import content_hash_for_bytes

        if not blob:
            missing_cache += 1
            continue
        if content_hash_for_bytes(blob) != content_hash:
            skipped += 1
            continue
        job = WorkJob.create(
            kind=STICKER_LABEL_JOB_KIND,
            payload={
                "content_hash": content_hash,
                "source": StickerLabelSource.RECOMMENDED_CANDIDATE.value,
                "prompt_version": STICKER_LABEL_PROMPT_VERSION,
                "observation": {"state": "queued"},
            },
            idempotency_key=f"{STICKER_LABEL_JOB_KIND}:{content_hash}:{STICKER_LABEL_PROMPT_VERSION}",
        )
        _, reactivated = await jobs.requeue_terminal(job)
        if reactivated:
            queued += 1
        else:
            skipped += 1
    consumed = queued + skipped + missing_cache
    used = sticker_label_backfill_account(consumed)
    return {
        "queued": queued,
        "skipped": skipped,
        "missing_cache": missing_cache,
        "budget_exhausted": False,
        "used": used,
    }


async def run_sticker_label_backfill_once(*, cfg=None) -> dict[str, int]:
    from pallas.product.llm.config import get_llm_config

    config = cfg or get_llm_config()
    if not bool(getattr(config, "llm_sticker_label_backfill_enabled", True)):
        return {"queued": 0, "skipped": 0, "missing_cache": 0, "budget_exhausted": True, "used": 0}
    if lazy_sticker_labels_paused():
        return {"queued": 0, "skipped": 0, "missing_cache": 0, "budget_exhausted": True, "used": 0}
    daily_limit = max(0, int(getattr(config, "llm_sticker_label_backfill_daily_limit", 200) or 0))
    if daily_limit <= 0:
        return {"queued": 0, "skipped": 0, "missing_cache": 0, "budget_exhausted": True, "used": 0}
    return await backfill_sticker_labels_batch(daily_limit=daily_limit)


def bind_sticker_label_backfill_lifecycle() -> None:
    global _STICKER_BACKFILL_LIFECYCLE_BOUND
    if _STICKER_BACKFILL_LIFECYCLE_BOUND:
        return
    _STICKER_BACKFILL_LIFECYCLE_BOUND = True
    from nonebot import get_driver

    driver = get_driver()

    @driver.on_startup
    async def _start_backfill_worker() -> None:
        async def _run() -> None:
            while True:
                try:
                    from pallas.core.platform.ingress.message_load import is_overloaded

                    if not is_overloaded():
                        await run_sticker_label_backfill_once()
                except Exception as exc:
                    logger.warning("sticker label backfill loop failed: {}", exc)
                await asyncio.sleep(_STICKER_BACKFILL_INTERVAL_SEC)

        task = asyncio.create_task(_run(), name="sticker_label_backfill_worker")
        driver._pallas_sticker_label_backfill_task = task

    @driver.on_shutdown
    async def _stop_backfill_worker() -> None:
        task = getattr(driver, "_pallas_sticker_label_backfill_task", None)
        if task is None:
            return
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        driver._pallas_sticker_label_backfill_task = None
