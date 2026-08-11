"""表情标签观测与维护；只基于标签表和已入队任务。"""

from __future__ import annotations

import asyncio
import time

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


def build_sticker_label_job_stats(records: list[dict[str, object]], *, recent_limit: int = 8) -> dict[str, object]:
    pending = failed = 0
    recent_errors: list[dict[str, object]] = []
    for row in sorted(records, key=lambda item: float(item.get("created_at") or 0), reverse=True):
        payload = row.get("payload") if isinstance(row.get("payload"), dict) else {}
        observation = payload.get("observation") if isinstance(payload.get("observation"), dict) else {}
        state = str(observation.get("state") or "queued")
        if state in {"queued", "running"}:
            pending += 1
        error = str(observation.get("error") or row.get("last_error") or "").strip()
        if error:
            failed += 1
            if len(recent_errors) < max(1, int(recent_limit)):
                recent_errors.append({
                    "job_id": str(row.get("job_id") or "")[:64],
                    "created_at": float(row.get("created_at") or 0),
                    "state": state,
                    "error": error[:240],
                })
    return {"pending": pending, "failed": failed, "recent_errors": recent_errors}


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
