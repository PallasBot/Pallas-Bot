from __future__ import annotations

import pytest


@pytest.mark.asyncio
async def test_requeue_stale_labels_only_queues_candidates_with_matching_cache(beanie_fixture) -> None:
    from pallas.core.foundation.db.modules import ImageCache, StickerLabel
    from pallas.core.foundation.db.repository_impl import MongoImageCacheRepository, MongoStickerLabelRepository
    from pallas.core.platform.work_jobs.store import MemoryWorkJobStore
    from pallas.product.llm.sticker_label_observability import requeue_stale_sticker_labels
    from pallas.product.llm.sticker_labels import StickerSemanticLabel, content_hash_for_bytes

    usable = b"usable-label-image"
    changed = b"changed-label-image"
    usable_hash = content_hash_for_bytes(usable)
    changed_hash = content_hash_for_bytes(changed)
    missing_hash = "f" * 64
    label_repo = MongoStickerLabelRepository()
    image_repo = MongoImageCacheRepository()
    store = MemoryWorkJobStore()
    for content_hash in (usable_hash, changed_hash, missing_hash):
        await StickerLabel(
            content_hash=content_hash,
            is_sticker=True,
            label_json=StickerSemanticLabel(content_hash=content_hash, is_sticker=True, confidence=0.2).model_dump(
                mode="json"
            ),
            confidence=0.2,
            prompt_version=0,
            labeled_at=0,
        ).insert()
    await ImageCache(cq_code="cache-usable", content_hash=usable_hash, blob_data=usable).insert()
    await ImageCache(cq_code="cache-changed", content_hash=changed_hash, blob_data=b"not-the-bound-content").insert()

    result = await requeue_stale_sticker_labels(
        label_repository=label_repo,
        image_cache_repository=image_repo,
        work_job_store=store,
    )

    assert result == {"requeued": 1, "queued": 1, "skipped": 1, "missing_cache": 1}
    claimed = await store.claim(owner="worker", lease_sec=1)
    assert claimed is not None
    assert claimed.payload["content_hash"] == usable_hash
    assert await store.claim(owner="worker", lease_sec=1) is None


@pytest.mark.asyncio
@pytest.mark.parametrize("leased", [False, True])
async def test_requeue_stale_labels_counts_active_jobs_as_skipped(beanie_fixture, leased: bool) -> None:
    from pallas.core.foundation.db.modules import ImageCache, StickerLabel
    from pallas.core.foundation.db.repository_impl import MongoImageCacheRepository, MongoStickerLabelRepository
    from pallas.core.platform.work_jobs.models import WorkJob
    from pallas.core.platform.work_jobs.store import MemoryWorkJobStore
    from pallas.product.llm.sticker_label_jobs import STICKER_LABEL_JOB_KIND, STICKER_LABEL_PROMPT_VERSION
    from pallas.product.llm.sticker_label_observability import requeue_stale_sticker_labels
    from pallas.product.llm.sticker_labels import StickerSemanticLabel, content_hash_for_bytes

    content = b"active-label-image"
    content_hash = content_hash_for_bytes(content)
    label_repo = MongoStickerLabelRepository()
    image_repo = MongoImageCacheRepository()
    store = MemoryWorkJobStore()
    await StickerLabel(
        content_hash=content_hash,
        is_sticker=True,
        label_json=StickerSemanticLabel(content_hash=content_hash, is_sticker=True, confidence=0.2).model_dump(
            mode="json"
        ),
        confidence=0.2,
        prompt_version=0,
        labeled_at=0,
    ).insert()
    await ImageCache(cq_code="cache-active", content_hash=content_hash, blob_data=content).insert()
    await store.enqueue(
        WorkJob.create(
            kind=STICKER_LABEL_JOB_KIND,
            payload={},
            idempotency_key=f"{STICKER_LABEL_JOB_KIND}:{content_hash}:{STICKER_LABEL_PROMPT_VERSION}",
        )
    )
    if leased:
        assert await store.claim(owner="worker", lease_sec=10)

    result = await requeue_stale_sticker_labels(
        label_repository=label_repo,
        image_cache_repository=image_repo,
        work_job_store=store,
    )

    assert result == {"requeued": 0, "queued": 0, "skipped": 1, "missing_cache": 0}


def test_sticker_label_backfill_account_tracks_daily_used(monkeypatch) -> None:
    from pallas.core.platform.shard.coord import coord_redis_store
    from pallas.product.llm import sticker_label_observability

    entries: dict[str, str] = {}

    class Pipeline:
        def __enter__(self):
            return self

        def __exit__(self, *_args: object) -> None:
            pass

        def watch(self, _key: str) -> None:
            pass

        def unwatch(self) -> None:
            pass

        def multi(self) -> None:
            pass

        def setex(self, key: str, _ttl: int, value: str) -> None:
            entries[key] = value

        def execute(self) -> list[bool]:
            return [True]

    class Redis:
        def get(self, key: str) -> str | None:
            return entries.get(key)

        def pipeline(self) -> Pipeline:
            return Pipeline()

        def delete(self, key: str) -> int:
            return int(entries.pop(key, None) is not None)

    monkeypatch.setattr(coord_redis_store, "redis_client_or_none", lambda: Redis())

    assert sticker_label_observability.sticker_label_backfill_used_today() == 0
    assert sticker_label_observability.sticker_label_backfill_account(5) == 5
    assert sticker_label_observability.sticker_label_backfill_account(3) == 8
    assert sticker_label_observability.sticker_label_backfill_used_today() == 8


@pytest.mark.asyncio
async def test_backfill_respects_daily_budget(monkeypatch: pytest.MonkeyPatch) -> None:
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    from pallas.product.llm import sticker_label_observability

    store = SimpleNamespace(requeue_terminal=AsyncMock(side_effect=lambda job: (job, True)))
    monkeypatch.setattr(sticker_label_observability, "build_work_job_store", lambda: store)
    monkeypatch.setattr(
        sticker_label_observability,
        "sticker_label_backfill_used_today",
        lambda: 180,
    )
    monkeypatch.setattr(
        sticker_label_observability,
        "list_unlabeled_content_hashes",
        AsyncMock(return_value=[f"{index:064x}" for index in range(10)]),
    )
    monkeypatch.setattr(
        sticker_label_observability,
        "sticker_label_backfill_account",
        lambda amount: 180 + amount,
    )

    def blob_for_hash(content_hash: str):
        return SimpleNamespace(blob_data=content_hash.encode())

    monkeypatch.setattr(
        "pallas.product.llm.sticker_labels.content_hash_for_bytes",
        lambda blob: blob.decode(),
        raising=False,
    )
    image_repo = SimpleNamespace(find_by_content_hash=AsyncMock(side_effect=blob_for_hash))
    label_repo = SimpleNamespace()

    result = await sticker_label_observability.backfill_sticker_labels_batch(
        daily_limit=200,
        batch_limit=10,
        label_repository=label_repo,
        image_cache_repository=image_repo,
        work_job_store=store,
    )

    assert result["queued"] == 10
    assert result["used"] == 190
    assert result["budget_exhausted"] is False


@pytest.mark.asyncio
async def test_backfill_stops_when_budget_exhausted(monkeypatch: pytest.MonkeyPatch) -> None:
    from unittest.mock import AsyncMock

    from pallas.product.llm import sticker_label_observability

    monkeypatch.setattr(sticker_label_observability, "sticker_label_backfill_used_today", lambda: 200)
    enqueue = AsyncMock()
    monkeypatch.setattr(sticker_label_observability, "list_unlabeled_content_hashes", enqueue)

    result = await sticker_label_observability.backfill_sticker_labels_batch(daily_limit=200)

    assert result["budget_exhausted"] is True
    assert result["queued"] == 0
    enqueue.assert_not_awaited()


def test_build_sticker_label_job_stats_counts_terminal_states_by_category() -> None:
    from pallas.product.llm.sticker_label_observability import build_sticker_label_job_stats

    records = [
        {
            "job_id": f"job-{state}",
            "created_at": float(index),
            "payload": {"observation": {"state": state, "error": f"err-{state}"}},
            "last_error": None,
        }
        for index, state in enumerate([
            "labeled",
            "labeled",
            "timeout",
            "parse_error",
            "no_vision",
            "failed",
            "circuit_open",
            "cache_changed",
        ])
    ]
    records.extend([
        {
            "job_id": "job-pending",
            "created_at": 100.0,
            "payload": {"observation": {"state": "queued"}},
            "last_error": None,
        },
        {
            "job_id": "job-running",
            "created_at": 101.0,
            "payload": {"observation": {"state": "running"}},
            "last_error": None,
        },
    ])

    stats = build_sticker_label_job_stats(records, recent_limit=3)

    assert stats["submitted"] == 10
    assert stats["labeled"] == 2
    assert stats["timeout"] == 1
    assert stats["parse_error"] == 1
    assert stats["no_vision"] == 1
    assert stats["failed"] == 1
    assert stats["circuit_open"] == 1
    assert stats["cache_changed"] == 1
    assert stats["pending"] == 2
    assert len(stats["recent_errors"]) == 3
