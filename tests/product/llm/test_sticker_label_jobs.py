from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest


def test_label_runtime_state_is_shared_by_producer_and_worker(monkeypatch: pytest.MonkeyPatch) -> None:
    from pallas.core.platform.shard.coord import coord_redis_store
    from pallas.product.llm import sticker_label_jobs

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

    sticker_label_jobs.reset_sticker_label_runtime_state_for_tests()
    assert sticker_label_jobs.set_lazy_sticker_labels_paused(True) is True
    assert sticker_label_jobs.lazy_sticker_labels_paused() is True
    assert len(entries) == 1

    for _ in range(sticker_label_jobs.STICKER_LABEL_CIRCUIT_FAILURES):
        sticker_label_jobs.sticker_label_circuit_record(False)
    assert sticker_label_jobs.sticker_label_circuit_open() is True
    assert '"failures":3' in entries[sticker_label_jobs.sticker_label_runtime_redis_key()]

    sticker_label_jobs.sticker_label_circuit_record(True)
    assert sticker_label_jobs.sticker_label_circuit_open() is False
    assert sticker_label_jobs.set_lazy_sticker_labels_paused(False) is False


@pytest.mark.asyncio
async def test_enqueue_candidate_uses_hash_locator_and_redacts_durable_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    from pallas.product.llm import sticker_label_jobs
    from pallas.product.llm.sticker_label_jobs import StickerLabelSource
    from pallas.product.llm.sticker_labels import content_hash_for_bytes

    original = b"original-gif-bytes"
    store = SimpleNamespace(requeue_terminal=AsyncMock(side_effect=lambda job: (job, True)))
    repository = SimpleNamespace(get=AsyncMock(return_value=None))
    monkeypatch.setattr(sticker_label_jobs, "build_work_job_store", lambda: store)
    monkeypatch.setattr(sticker_label_jobs, "sticker_label_repository", lambda: repository)
    monkeypatch.setattr("pallas.core.shared.utils.media_cache.bind_image_content_hash", AsyncMock())

    queued = await sticker_label_jobs.enqueue_sticker_label_candidate(
        cache_key="[CQ:image,file=candidate.image,user_id=10086]",
        content=original,
        source=StickerLabelSource.REPEATER_CANDIDATE,
    )

    assert queued is True
    job = store.requeue_terminal.await_args.args[0]
    assert job.kind == "sticker.label.visual"
    assert job.idempotency_key == f"sticker.label.visual:{content_hash_for_bytes(original)}:1"
    assert job.payload == {
        "content_hash": content_hash_for_bytes(original),
        "source": StickerLabelSource.REPEATER_CANDIDATE.value,
        "prompt_version": 1,
        "observation": {"state": "queued"},
    }
    serialized = repr(job.payload)
    for forbidden in ("CQ:", "candidate.image", "user_id", "group_id", "message", original.decode()):
        assert forbidden not in serialized


@pytest.mark.asyncio
async def test_high_confidence_current_negative_label_does_not_requeue(monkeypatch: pytest.MonkeyPatch) -> None:
    from pallas.product.llm import sticker_label_jobs
    from pallas.product.llm.sticker_label_jobs import StickerLabelSource
    from pallas.product.llm.sticker_labels import StickerSemanticLabel, content_hash_for_bytes

    content = b"not-a-sticker"
    repository = SimpleNamespace(
        get=AsyncMock(
            return_value=StickerSemanticLabel(
                content_hash=content_hash_for_bytes(content),
                is_sticker=False,
                confidence=0.9,
                prompt_version=1,
            )
        )
    )
    store = SimpleNamespace(requeue_terminal=AsyncMock())
    monkeypatch.setattr(sticker_label_jobs, "sticker_label_repository", lambda: repository)
    monkeypatch.setattr(sticker_label_jobs, "build_work_job_store", lambda: store)

    assert not await sticker_label_jobs.enqueue_sticker_label_candidate(
        cache_key="[CQ:image,file=not-sticker.image]", content=content, source=StickerLabelSource.MANUAL_STICKER
    )
    store.requeue_terminal.assert_not_awaited()


@pytest.mark.asyncio
async def test_low_confidence_or_old_prompt_label_requeues(monkeypatch: pytest.MonkeyPatch) -> None:
    from pallas.product.llm import sticker_label_jobs
    from pallas.product.llm.sticker_label_jobs import StickerLabelSource
    from pallas.product.llm.sticker_labels import StickerSemanticLabel, content_hash_for_bytes

    content = b"needs-relabel"
    repository = SimpleNamespace(
        get=AsyncMock(
            return_value=StickerSemanticLabel(
                content_hash=content_hash_for_bytes(content),
                is_sticker=True,
                confidence=0.5,
                prompt_version=0,
            )
        )
    )
    store = SimpleNamespace(requeue_terminal=AsyncMock(side_effect=lambda job: (job, True)))
    monkeypatch.setattr(sticker_label_jobs, "sticker_label_repository", lambda: repository)
    monkeypatch.setattr(sticker_label_jobs, "build_work_job_store", lambda: store)
    monkeypatch.setattr("pallas.core.shared.utils.media_cache.bind_image_content_hash", AsyncMock())

    assert await sticker_label_jobs.enqueue_sticker_label_candidate(
        cache_key="[CQ:image,file=old.image]", content=content, source=StickerLabelSource.FOLLOWUP_CANDIDATE
    )
    store.requeue_terminal.assert_awaited_once()


@pytest.mark.asyncio
async def test_enqueue_candidate_counts_cache_hit_when_label_is_sufficient(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from pallas.product.llm import sticker_label_jobs
    from pallas.product.llm.sticker_label_jobs import StickerLabelSource
    from pallas.product.llm.sticker_labels import StickerSemanticLabel, content_hash_for_bytes
    from pallas.product.llm.task_metrics import record_bot_llm_task

    content = b"already-labeled"
    repository = SimpleNamespace(
        get=AsyncMock(
            return_value=StickerSemanticLabel(
                content_hash=content_hash_for_bytes(content),
                is_sticker=True,
                confidence=0.95,
                prompt_version=1,
            )
        )
    )
    store = SimpleNamespace(requeue_terminal=AsyncMock())
    metric = Mock()
    monkeypatch.setattr(sticker_label_jobs, "sticker_label_repository", lambda: repository)
    monkeypatch.setattr(sticker_label_jobs, "build_work_job_store", lambda: store)
    monkeypatch.setattr("pallas.product.llm.task_metrics.record_bot_llm_task", metric)

    assert not await sticker_label_jobs.enqueue_sticker_label_candidate(
        cache_key="[CQ:image,file=already-labeled.image]",
        content=content,
        source=StickerLabelSource.FOLLOWUP_CANDIDATE,
    )
    store.requeue_terminal.assert_not_awaited()
    metric.assert_any_call("sticker_label", "cache_hit")
    assert not any(call.args[1] == "submit_ok" for call in metric.call_args_list)
    assert record_bot_llm_task is not None


@pytest.mark.asyncio
async def test_enqueue_candidate_counts_coalesced_when_job_already_pending(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from pallas.product.llm import sticker_label_jobs
    from pallas.product.llm.sticker_label_jobs import StickerLabelSource

    content = b"dup-content"
    repository = SimpleNamespace(get=AsyncMock(return_value=None))
    store = SimpleNamespace(requeue_terminal=AsyncMock(side_effect=lambda job: (job, False)))
    metric = Mock()
    monkeypatch.setattr(sticker_label_jobs, "sticker_label_repository", lambda: repository)
    monkeypatch.setattr(sticker_label_jobs, "build_work_job_store", lambda: store)
    monkeypatch.setattr("pallas.core.shared.utils.media_cache.bind_image_content_hash", AsyncMock())
    monkeypatch.setattr("pallas.product.llm.task_metrics.record_bot_llm_task", metric)

    queued = await sticker_label_jobs.enqueue_sticker_label_candidate(
        cache_key="[CQ:image,file=dup.image]",
        content=content,
        source=StickerLabelSource.FOLLOWUP_CANDIDATE,
    )

    assert queued is True
    assert not any(call.args[1] == "submit_ok" for call in metric.call_args_list)
    assert any(call.args == ("sticker_label", "background_coalesced") for call in metric.call_args_list)


@pytest.mark.asyncio
async def test_string_source_cannot_enqueue_a_label_job(monkeypatch: pytest.MonkeyPatch) -> None:
    from pallas.product.llm import sticker_label_jobs

    store = SimpleNamespace(requeue_terminal=AsyncMock())
    monkeypatch.setattr(sticker_label_jobs, "build_work_job_store", lambda: store)

    assert not await sticker_label_jobs.enqueue_sticker_label_candidate(
        cache_key="[CQ:image,file=ordinary.image]", content=b"ordinary", source="test_candidate"
    )
    store.requeue_terminal.assert_not_awaited()


def test_parse_visual_label_requires_strict_json_schema() -> None:
    from pallas.product.llm.sticker_label_jobs import parse_sticker_visual_label

    label = parse_sticker_visual_label(
        '{"is_sticker":true,"emotions":["开心"],"actions":["挥手"],"tones":["可爱"],'
        '"intensity":2,"usage":["打招呼"],"avoid":["严肃场合"],"caption":"挥手小猫","confidence":0.8}'
    )

    assert label["is_sticker"] is True
    assert label["emotions"] == ("开心",)
    assert parse_sticker_visual_label('{"is_sticker": true}') is None
    assert parse_sticker_visual_label("不是 JSON") is None


def test_parse_visual_label_accepts_partial_and_extra_fields() -> None:
    from pallas.product.llm.sticker_label_jobs import parse_sticker_visual_label

    label = parse_sticker_visual_label(
        '{"is_sticker":true,"emotions":["开心","难过"],"actions":"挥手",'
        '"intensity":2,"usage":"打招呼","confidence":0.8,"extra":"ignored"}'
    )

    assert label is not None
    assert label["is_sticker"] is True
    assert label["emotions"] == ("开心", "难过")
    assert label["actions"] == ("挥手",)
    assert label["usage"] == ("打招呼",)
    assert label["tones"] == ()
    assert label["avoid"] == ()
    assert label["caption"] == ""
    assert label["confidence"] == 0.8
    assert "extra" not in label


def test_parse_visual_label_accepts_comma_separated_array_fields() -> None:
    from pallas.product.llm.sticker_label_jobs import parse_sticker_visual_label

    label = parse_sticker_visual_label(
        '{"is_sticker":true,"emotions":"开心, 难过","actions":"微笑,大笑",'
        '"tones":"可爱,友好","usage":"适合聊天","avoid":"别在严肃场合","caption":"挥手","confidence":0.7}'
    )

    assert label is not None
    assert label["emotions"] == ("开心", "难过")
    assert label["actions"] == ("微笑", "大笑")
    assert label["tones"] == ("可爱", "友好")
    assert label["usage"] == ("适合聊天",)
    assert label["avoid"] == ("别在严肃场合",)


def test_parse_visual_label_requires_confidence_and_boolean() -> None:
    from pallas.product.llm.sticker_label_jobs import parse_sticker_visual_label

    assert parse_sticker_visual_label('{"is_sticker":true}') is None
    assert parse_sticker_visual_label('{"is_sticker":"yes","confidence":0.8}') is None
    assert parse_sticker_visual_label('{"is_sticker":true,"confidence":"high"}') is None


@pytest.mark.asyncio
async def test_worker_marks_cache_changed_complete_without_calling_vision(monkeypatch: pytest.MonkeyPatch) -> None:
    from pallas.product.llm import sticker_label_jobs
    from pallas.product.llm.sticker_labels import content_hash_for_bytes

    complete = AsyncMock()
    monkeypatch.setattr(
        "pallas.core.shared.utils.media_cache.get_image_by_content_hash", AsyncMock(return_value=b"changed")
    )
    monkeypatch.setattr(sticker_label_jobs, "label_sticker_with_vision", complete)
    monkeypatch.setattr(sticker_label_jobs, "save_sticker_label_observation", AsyncMock())

    await sticker_label_jobs.handle_sticker_label_visual({
        "job_id": "job-1",
        "content_hash": content_hash_for_bytes(b"original"),
        "prompt_version": 1,
        "observation": {"state": "queued"},
    })
    complete.assert_not_awaited()


@pytest.mark.asyncio
async def test_terminal_label_job_is_reactivated_with_same_idempotency_key() -> None:
    from pallas.core.platform.work_jobs.models import WorkJob
    from pallas.core.platform.work_jobs.store import MemoryWorkJobStore

    store = MemoryWorkJobStore()
    await store.enqueue(WorkJob.create(kind="sticker.label.visual", payload={}, idempotency_key="label:hash:1"))
    claimed = await store.claim(owner="worker", lease_sec=1)
    assert claimed is not None
    assert await store.dead_letter(job_id=claimed.id, owner="worker", lease_id=claimed.lease_id or "", reason="bad")

    replacement = WorkJob.create(
        kind="sticker.label.visual",
        payload={"content_hash": "a" * 64},
        idempotency_key="label:hash:1",
    )
    reactivated, was_reactivated = await store.requeue_terminal(replacement)

    assert reactivated.id == replacement.id
    assert was_reactivated is True
    next_claim = await store.claim(owner="worker-2", lease_sec=1)
    assert next_claim is not None
    assert next_claim.id == replacement.id


@pytest.mark.asyncio
async def test_inflight_label_job_is_not_reactivated() -> None:
    from pallas.core.platform.work_jobs.models import WorkJob
    from pallas.core.platform.work_jobs.store import MemoryWorkJobStore

    store = MemoryWorkJobStore()
    first = await store.enqueue(
        WorkJob.create(kind="sticker.label.visual", payload={}, idempotency_key="label:inflight:1")
    )
    assert await store.claim(owner="worker", lease_sec=10)

    reactivated, was_reactivated = await store.requeue_terminal(
        WorkJob.create(kind="sticker.label.visual", payload={}, idempotency_key="label:inflight:1")
    )

    assert reactivated.id == first.id
    assert was_reactivated is False
    assert await store.claim(owner="worker-2", lease_sec=1) is None


def test_label_runtime_is_isolated_from_online_sticker_selection() -> None:
    from pallas.product.llm import sticker_label_jobs, sticker_vision

    assert sticker_label_jobs._STICKER_LABEL_SEMAPHORE is not sticker_vision._VISION_SELECT_SEMAPHORE


@pytest.mark.asyncio
async def test_label_circuit_suppresses_producer_and_worker_calls(monkeypatch: pytest.MonkeyPatch) -> None:
    from pallas.product.llm import sticker_label_jobs
    from pallas.product.llm.sticker_labels import content_hash_for_bytes

    sticker_label_jobs.reset_sticker_label_runtime_state_for_tests()
    monkeypatch.setattr(
        "pallas.core.shared.utils.media_cache.get_image_by_content_hash", AsyncMock(return_value=b"image")
    )
    monkeypatch.setattr(sticker_label_jobs, "label_sticker_with_vision", AsyncMock(side_effect=TimeoutError("slow")))
    monkeypatch.setattr(sticker_label_jobs, "save_sticker_label_observation", AsyncMock())
    for _ in range(sticker_label_jobs.STICKER_LABEL_CIRCUIT_FAILURES):
        with pytest.raises(TimeoutError):
            await sticker_label_jobs.handle_sticker_label_visual({
                "job_id": "job-1",
                "content_hash": content_hash_for_bytes(b"image"),
                "observation": {},
            })
    assert sticker_label_jobs.sticker_label_circuit_open()

    repository = SimpleNamespace(get=AsyncMock(return_value=None))
    store = SimpleNamespace(requeue_terminal=AsyncMock())
    monkeypatch.setattr(sticker_label_jobs, "sticker_label_repository", lambda: repository)
    monkeypatch.setattr(sticker_label_jobs, "build_work_job_store", lambda: store)
    assert not await sticker_label_jobs.enqueue_sticker_label_candidate(
        cache_key="[CQ:image,file=should-not-resolve.image]",
        content=b"image",
        source=sticker_label_jobs.StickerLabelSource.TEST_CANDIDATE,
    )
    store.requeue_terminal.assert_not_awaited()

    get_image = AsyncMock()
    monkeypatch.setattr("pallas.core.shared.utils.media_cache.get_image_by_content_hash", get_image)
    await sticker_label_jobs.handle_sticker_label_visual({
        "job_id": "job-2",
        "content_hash": "a" * 64,
        "observation": {},
    })
    get_image.assert_not_awaited()
    sticker_label_jobs.reset_sticker_label_runtime_state_for_tests()


@pytest.mark.asyncio
async def test_saturated_label_semaphore_times_out_retries_and_releases_lease(monkeypatch: pytest.MonkeyPatch) -> None:
    from pallas.core.platform.work_jobs.models import WorkJob
    from pallas.core.platform.work_jobs.store import MemoryWorkJobStore
    from pallas.core.platform.work_jobs.worker import WorkJobWorker
    from pallas.product.llm import sticker_label_jobs
    from pallas.product.llm.sticker_labels import content_hash_for_bytes

    sticker_label_jobs.reset_sticker_label_runtime_state_for_tests()
    semaphore = asyncio.Semaphore(1)
    await semaphore.acquire()
    monkeypatch.setattr(sticker_label_jobs, "_STICKER_LABEL_SEMAPHORE", semaphore)
    monkeypatch.setattr(sticker_label_jobs, "STICKER_LABEL_TIMEOUT_SEC", 0.01)
    save_observation = AsyncMock()
    monkeypatch.setattr(sticker_label_jobs, "save_sticker_label_observation", save_observation)
    monkeypatch.setattr(
        "pallas.core.shared.utils.media_cache.get_image_by_content_hash", AsyncMock(return_value=b"image")
    )
    store = MemoryWorkJobStore()
    await store.enqueue(
        WorkJob.create(
            kind="sticker.label.visual",
            payload={"content_hash": content_hash_for_bytes(b"image"), "observation": {"state": "queued"}},
            idempotency_key="label:semaphore-timeout",
        )
    )
    worker = WorkJobWorker(
        store=store,
        owner="worker",
        handlers={"sticker.label.visual": sticker_label_jobs.handle_sticker_label_visual},
        retry_after_sec=0,
    )

    assert await worker.run_once()
    assert save_observation.await_args.args[2]["state"] == "timeout"
    assert sticker_label_jobs.sticker_label_circuit_open() is False
    assert (await store.stats())["leased"] == 0
    assert await store.claim(owner="next", lease_sec=1) is not None
    semaphore.release()
    sticker_label_jobs.reset_sticker_label_runtime_state_for_tests()


@pytest.mark.asyncio
async def test_cancelling_visual_label_releases_semaphore_without_retrying_worker(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from pallas.core.platform.work_jobs.models import WorkJob
    from pallas.core.platform.work_jobs.store import MemoryWorkJobStore
    from pallas.core.platform.work_jobs.worker import WorkJobWorker
    from pallas.product.llm import sticker_label_jobs
    from pallas.product.llm.sticker_labels import content_hash_for_bytes

    sticker_label_jobs.reset_sticker_label_runtime_state_for_tests()
    semaphore = asyncio.Semaphore(1)
    monkeypatch.setattr(sticker_label_jobs, "_STICKER_LABEL_SEMAPHORE", semaphore)
    monkeypatch.setattr(
        "pallas.core.shared.utils.media_cache.get_image_by_content_hash", AsyncMock(return_value=b"image")
    )
    vision_started = asyncio.Event()

    async def wait_for_vision(_content: bytes):
        vision_started.set()
        await asyncio.Event().wait()

    task_metric = Mock()
    monkeypatch.setattr(sticker_label_jobs, "label_sticker_with_vision", wait_for_vision)
    monkeypatch.setattr("pallas.product.llm.task_metrics.record_bot_llm_task", task_metric)
    store = MemoryWorkJobStore()
    await store.enqueue(
        WorkJob.create(
            kind="sticker.label.visual",
            payload={"content_hash": content_hash_for_bytes(b"image"), "observation": {"state": "queued"}},
            idempotency_key="label:cancelled-vision",
        )
    )
    worker = WorkJobWorker(
        store=store,
        owner="worker",
        handlers={"sticker.label.visual": sticker_label_jobs.handle_sticker_label_visual},
        retry_after_sec=0,
    )
    run_task = asyncio.create_task(worker.run_once())
    await vision_started.wait()

    run_task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await run_task

    assert semaphore.locked() is False
    assert task_metric.call_args_list == []
    assert sticker_label_jobs.sticker_label_circuit_open() is False
    assert worker.metrics.snapshot()["retried_since_start"] == 0
    sticker_label_jobs.reset_sticker_label_runtime_state_for_tests()


@pytest.mark.asyncio
async def test_cache_changed_is_completed_by_actual_worker(monkeypatch: pytest.MonkeyPatch) -> None:
    from pallas.core.platform.work_jobs.models import WorkJob
    from pallas.core.platform.work_jobs.store import MemoryWorkJobStore
    from pallas.core.platform.work_jobs.worker import WorkJobWorker
    from pallas.product.llm import sticker_label_jobs
    from pallas.product.llm.sticker_labels import content_hash_for_bytes

    store = MemoryWorkJobStore()
    await store.enqueue(
        WorkJob.create(
            kind="sticker.label.visual",
            payload={"content_hash": content_hash_for_bytes(b"original"), "observation": {"state": "queued"}},
            idempotency_key="label:cache-changed",
        )
    )
    monkeypatch.setattr(
        "pallas.core.shared.utils.media_cache.get_image_by_content_hash", AsyncMock(return_value=b"changed")
    )
    monkeypatch.setattr(sticker_label_jobs, "save_sticker_label_observation", AsyncMock())
    worker = WorkJobWorker(
        store=store, owner="worker", handlers={"sticker.label.visual": sticker_label_jobs.handle_sticker_label_visual}
    )

    assert await worker.run_once()
    assert await store.claim(owner="other", lease_sec=1) is None


@pytest.mark.asyncio
async def test_permanent_label_errors_do_not_retry_worker(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from pallas.core.platform.work_jobs.models import WorkJob
    from pallas.core.platform.work_jobs.store import MemoryWorkJobStore
    from pallas.core.platform.work_jobs.worker import WorkJobWorker
    from pallas.product.llm import sticker_label_jobs
    from pallas.product.llm.sticker_labels import content_hash_for_bytes

    sticker_label_jobs.reset_sticker_label_runtime_state_for_tests()
    for case in ("parse_error", "no_vision"):
        save_observation = AsyncMock()
        monkeypatch.setattr(sticker_label_jobs, "save_sticker_label_observation", save_observation)
        monkeypatch.setattr(
            "pallas.core.shared.utils.media_cache.get_image_by_content_hash", AsyncMock(return_value=b"image")
        )

        def build_fail_vision(mode: str):
            async def fail_vision(_content: bytes) -> None:
                if mode == "parse_error":
                    raise ValueError("invalid sticker label JSON")
                raise RuntimeError("no sticker vision endpoint")

            return fail_vision

        monkeypatch.setattr(sticker_label_jobs, "label_sticker_with_vision", build_fail_vision(case))
        store = MemoryWorkJobStore()
        await store.enqueue(
            WorkJob.create(
                kind="sticker.label.visual",
                payload={"content_hash": content_hash_for_bytes(b"image"), "observation": {"state": "queued"}},
                idempotency_key=f"label:permanent:{case}",
            )
        )
        worker = WorkJobWorker(
            store=store,
            owner="worker",
            handlers={"sticker.label.visual": sticker_label_jobs.handle_sticker_label_visual},
        )

        assert await worker.run_once()
        assert (await store.stats())["leased"] == 0
        assert (await store.stats())["dead_lettered"] == 0
        assert worker.metrics.snapshot()["retried_since_start"] == 0
        assert (await store.stats())["pending"] == 0
        assert await store.claim(owner="next", lease_sec=1) is None
        assert save_observation.await_args.args[2]["state"] in {"parse_error", "no_vision"}
    sticker_label_jobs.reset_sticker_label_runtime_state_for_tests()


@pytest.mark.asyncio
async def test_content_rejection_records_negative_label_without_retry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from pallas.product.llm import sticker_label_jobs
    from pallas.product.llm.provider_client import LlmProviderError
    from pallas.product.llm.sticker_labels import content_hash_for_bytes

    sticker_label_jobs.reset_sticker_label_runtime_state_for_tests()
    content = b"nsfw-content"
    content_hash = content_hash_for_bytes(content)
    save_observation = AsyncMock()
    repository = SimpleNamespace(upsert=AsyncMock())
    monkeypatch.setattr(sticker_label_jobs, "sticker_label_repository", lambda: repository)
    monkeypatch.setattr(sticker_label_jobs, "save_sticker_label_observation", save_observation)
    monkeypatch.setattr(
        "pallas.core.shared.utils.media_cache.get_image_by_content_hash", AsyncMock(return_value=content)
    )
    monkeypatch.setattr(
        sticker_label_jobs.sticker_label_runtime_state,
        "sticker_label_circuit_open",
        lambda *, now=None: False,
    )

    async def reject_content(_content: bytes) -> None:
        raise LlmProviderError(
            'Input image data may contain inappropriate content. {"code":"data_inspection_failed"}',
            status=400,
        )

    monkeypatch.setattr(sticker_label_jobs, "label_sticker_with_vision", reject_content)

    await sticker_label_jobs.handle_sticker_label_visual({
        "job_id": "job-rejected",
        "content_hash": content_hash,
        "prompt_version": 1,
        "observation": {"state": "queued"},
    })

    assert save_observation.await_args.args[2]["state"] == "rejected"
    observation = save_observation.await_args.args[2]
    assert observation["is_sticker"] is False
    assert repository.upsert.await_args.args[0].is_sticker is False
    assert sticker_label_jobs.sticker_label_circuit_open() is False
    sticker_label_jobs.reset_sticker_label_runtime_state_for_tests()


@pytest.mark.asyncio
async def test_parse_error_does_not_open_circuit(monkeypatch: pytest.MonkeyPatch) -> None:
    from pallas.product.llm import sticker_label_jobs
    from pallas.product.llm.sticker_labels import content_hash_for_bytes

    sticker_label_jobs.reset_sticker_label_runtime_state_for_tests()
    monkeypatch.setattr(sticker_label_jobs, "save_sticker_label_observation", AsyncMock())
    monkeypatch.setattr(
        "pallas.core.shared.utils.media_cache.get_image_by_content_hash", AsyncMock(return_value=b"image")
    )

    async def invalid_json(_content: bytes) -> None:
        raise ValueError("invalid sticker label JSON")

    monkeypatch.setattr(sticker_label_jobs, "label_sticker_with_vision", invalid_json)

    for _ in range(sticker_label_jobs.STICKER_LABEL_CIRCUIT_FAILURES + 1):
        await sticker_label_jobs.handle_sticker_label_visual({
            "job_id": "job-parse",
            "content_hash": content_hash_for_bytes(b"image"),
            "prompt_version": 1,
            "observation": {},
        })

    assert sticker_label_jobs.sticker_label_circuit_open() is False
    sticker_label_jobs.reset_sticker_label_runtime_state_for_tests()
