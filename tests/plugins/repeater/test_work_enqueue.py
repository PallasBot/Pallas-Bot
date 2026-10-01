from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest


@pytest.fixture(autouse=True)
def reset_message_load_state() -> None:
    from pallas.core.platform.ingress.message_load import reset_message_load_for_tests

    reset_message_load_for_tests()
    yield
    reset_message_load_for_tests()


def _chat_data(**overrides):
    from packages.repeater.model import ChatData

    base = {
        "group_id": 42,
        "user_id": 11,
        "bot_id": 100,
        "raw_message": "这一句",
        "plain_text": "这一句",
        "time": 20,
    }
    base.update(overrides)
    return ChatData(**base)


@pytest.mark.asyncio
async def test_enqueue_repeater_learn_captures_idempotent_work_job(monkeypatch: pytest.MonkeyPatch) -> None:
    from packages.repeater import learn_queue
    from pallas.core.platform.ingress import hotpath_metrics

    payload = SimpleNamespace(
        to_dict=lambda: {
            "chat": {"group_id": 42, "user_id": 12, "bot_id": 100, "plain_text": "接话", "time": 20},
            "predecessor": {"user_id": 11, "plain_text": "前句"},
        }
    )
    chat = SimpleNamespace(chat_data=_chat_data())
    event = SimpleNamespace(group_id=42, message_id=99, self_id=100)
    monkeypatch.setattr(learn_queue, "claim_group_message_event", AsyncMock(return_value=True))
    monkeypatch.setattr("packages.repeater.learner.Learner.capture_for_work", AsyncMock(return_value=payload))
    monkeypatch.setattr(
        "packages.repeater.learner.Learner.capture_message_for_persist", AsyncMock(return_value={"message": 1})
    )
    learn_queue.clear_repeater_learn_runtime_state()
    hotpath_metrics.clear_hotpath_metrics_for_tests()

    assert await learn_queue.enqueue_repeater_learn(chat, event) is True

    learn_job = learn_queue.learn_queue().get_nowait()
    assert learn_job.kind == "repeater.learn"
    assert learn_job.idempotency_key == "repeater.learn:42:99:100"
    assert learn_job.payload == payload.to_dict()
    assert hotpath_metrics.hotpath_metrics_snapshot()["learn_enqueued"] == 1
    assert hotpath_metrics.hotpath_metrics_snapshot()["learn_buffered"] == 1


@pytest.mark.asyncio
async def test_enqueue_repeater_learn_buffers_job_without_waiting_for_outbox(monkeypatch: pytest.MonkeyPatch) -> None:
    from packages.repeater import learn_queue

    learn_queue.clear_repeater_learn_runtime_state()
    payload = SimpleNamespace(
        to_dict=lambda: {
            "chat": {"group_id": 42, "user_id": 12, "bot_id": 100, "plain_text": "接话", "time": 20},
            "predecessor": {"user_id": 11, "plain_text": "前句"},
        }
    )
    chat = SimpleNamespace(chat_data=_chat_data())
    event = SimpleNamespace(group_id=42, message_id=99, self_id=100)
    store = SimpleNamespace(enqueue_many=AsyncMock())
    monkeypatch.setattr(learn_queue, "claim_group_message_event", AsyncMock(return_value=True))
    monkeypatch.setattr("packages.repeater.learner.Learner.capture_for_work", AsyncMock(return_value=payload))
    monkeypatch.setattr(
        "packages.repeater.learner.Learner.capture_message_for_persist", AsyncMock(return_value={"message": 1})
    )
    monkeypatch.setattr(learn_queue, "build_work_job_store", lambda: store)

    assert await learn_queue.enqueue_repeater_learn(chat, event) is True

    store.enqueue_many.assert_not_awaited()
    assert learn_queue.learn_queue().qsize() == 1


@pytest.mark.asyncio
async def test_enqueue_repeater_learn_skips_capture_under_pressure_but_keeps_message_persist(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from packages.repeater import learn_queue
    from pallas.core.platform.ingress import hotpath_metrics

    chat = SimpleNamespace(chat_data=_chat_data())
    event = SimpleNamespace(group_id=42, message_id=99, self_id=100)
    capture = AsyncMock(return_value=None)
    message_capture = AsyncMock(return_value={"message": {"group_id": 42}})
    monkeypatch.setattr(learn_queue, "claim_group_message_event", AsyncMock(return_value=True))
    monkeypatch.setattr(learn_queue, "should_skip_repeater_learn_enqueue", lambda: True)
    monkeypatch.setattr("packages.repeater.learner.Learner.capture_for_work", capture)
    monkeypatch.setattr("packages.repeater.learner.Learner.capture_message_for_persist", message_capture)
    learn_queue.clear_repeater_learn_runtime_state()
    hotpath_metrics.clear_hotpath_metrics_for_tests()

    assert await learn_queue.enqueue_repeater_learn(chat, event) is False

    message_capture.assert_awaited_once()
    capture.assert_not_awaited()
    jobs = [learn_queue.message_queue().get_nowait()]
    assert [job.kind for job in jobs] == ["repeater.message"]
    assert hotpath_metrics.hotpath_metrics_snapshot()["learn_skipped_pressure"] == 1
    assert hotpath_metrics.hotpath_metrics_snapshot()["message_persist_buffered"] == 1


@pytest.mark.asyncio
async def test_repeater_outbox_writer_flushes_buffered_jobs_as_a_batch(monkeypatch: pytest.MonkeyPatch) -> None:
    from packages.repeater import learn_queue
    from pallas.core.platform.work_jobs.models import WorkJob

    learn_queue.clear_repeater_learn_runtime_state()
    store = SimpleNamespace(enqueue_many=AsyncMock())
    monkeypatch.setattr(learn_queue, "build_work_job_store", lambda: store)
    monkeypatch.setattr(learn_queue, "wait_pg_pool_headroom_for_learn", AsyncMock())
    first = WorkJob.create(kind="repeater.learn", payload={"id": 1}, idempotency_key="repeater:1")
    second = WorkJob.create(kind="repeater.learn", payload={"id": 2}, idempotency_key="repeater:2")
    learn_queue.learn_queue().put_nowait(first)
    learn_queue.learn_queue().put_nowait(second)
    writer = asyncio.create_task(learn_queue.run_learn_consumer())

    try:
        for _ in range(20):
            if store.enqueue_many.await_count:
                break
            await asyncio.sleep(0.01)
        store.enqueue_many.assert_awaited_once_with([first, second])
    finally:
        writer.cancel()
        await asyncio.gather(writer, return_exceptions=True)


@pytest.mark.asyncio
async def test_repeater_outbox_writer_normalizes_nul_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    from packages.repeater import learn_queue
    from pallas.core.platform.work_jobs.models import WorkJob

    learn_queue.clear_repeater_learn_runtime_state()
    store = SimpleNamespace(enqueue_many=AsyncMock())
    monkeypatch.setattr(learn_queue, "is_postgresql_backend", lambda: True)
    monkeypatch.setattr(learn_queue, "build_work_job_store", lambda: store)
    monkeypatch.setattr(learn_queue, "wait_pg_pool_headroom_for_learn", AsyncMock())
    learn_queue.learn_queue().put_nowait(
        WorkJob.create(kind="repeater.learn", payload={"raw_message": "bad\x00payload"}, idempotency_key="repeater:nul")
    )
    queue = learn_queue.learn_queue()
    writer = asyncio.create_task(learn_queue.run_learn_consumer())

    try:
        await asyncio.wait_for(queue.join(), timeout=0.2)
        store.enqueue_many.assert_awaited_once()
        persisted_job = store.enqueue_many.await_args.args[0][0]
        assert persisted_job.payload == {"raw_message": "badpayload"}
    finally:
        writer.cancel()
        await asyncio.gather(writer, return_exceptions=True)


@pytest.mark.asyncio
async def test_repeater_outbox_isolates_permanent_payload_after_transient_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from packages.repeater import learn_queue
    from pallas.core.platform.work_jobs.models import InvalidWorkJobPayloadError, WorkJob, normalize_work_job_payload

    learn_queue.clear_repeater_learn_runtime_state()
    attempts = 0
    persisted: list[WorkJob] = []
    warnings: list[str] = []
    bad = WorkJob.create(kind="repeater.learn", payload={"message": "bad"}, idempotency_key="repeater:bad")
    good = WorkJob.create(kind="repeater.learn", payload={"message": "good"}, idempotency_key="repeater:good")

    class Store:
        async def enqueue_many(self, jobs: list[WorkJob]) -> None:
            nonlocal attempts
            attempts += 1
            if attempts == 1:
                jobs[0].payload.update({"key\x00": "PAYLOAD_SENTINEL", "key": "collision"})
                raise RuntimeError("temporary database outage")
            for job in jobs:
                try:
                    normalize_work_job_payload(job.payload)
                except InvalidWorkJobPayloadError as exc:
                    raise InvalidWorkJobPayloadError(f"{exc} PAYLOAD_SENTINEL") from exc
            persisted.extend(jobs)

    monkeypatch.setattr(learn_queue, "build_work_job_store", Store)
    monkeypatch.setattr(learn_queue, "wait_pg_pool_headroom_for_learn", AsyncMock())
    monkeypatch.setattr(learn_queue.logger, "warning", lambda *args: warnings.append(" ".join(map(str, args))))
    learn_queue.learn_queue().put_nowait(bad)
    learn_queue.learn_queue().put_nowait(good)
    queue = learn_queue.learn_queue()
    writer = asyncio.create_task(learn_queue.run_learn_consumer())

    try:
        await asyncio.wait_for(queue.join(), timeout=0.5)
        assert attempts == 3
        assert persisted == [good]
        assert "PAYLOAD_SENTINEL" not in " ".join(warnings)
    finally:
        writer.cancel()
        await asyncio.gather(writer, return_exceptions=True)
        learn_queue.clear_repeater_learn_runtime_state()


@pytest.mark.asyncio
async def test_repeater_outbox_backoff_stays_capped_after_prolonged_outage(monkeypatch: pytest.MonkeyPatch) -> None:
    from packages.repeater import learn_queue
    from pallas.core.platform.work_jobs.models import WorkJob

    learn_queue.clear_repeater_learn_runtime_state()
    attempts = 0
    persisted: list[WorkJob] = []
    delays: list[float] = []
    real_sleep = asyncio.sleep

    class Store:
        async def enqueue_many(self, jobs: list[WorkJob]) -> None:
            nonlocal attempts
            attempts += 1
            if attempts <= 1100:
                raise RuntimeError("temporary database outage")
            persisted.extend(jobs)

    async def fast_sleep(delay: float) -> None:
        delays.append(delay)
        await real_sleep(0)

    monkeypatch.setattr(learn_queue, "is_postgresql_backend", lambda: True)
    monkeypatch.setattr(learn_queue, "build_work_job_store", Store)
    monkeypatch.setattr(learn_queue, "wait_pg_pool_headroom_for_learn", AsyncMock())
    monkeypatch.setattr(learn_queue.asyncio, "sleep", fast_sleep)
    job = WorkJob.create(kind="repeater.learn", payload={}, idempotency_key="repeater:long-outage")
    queue = learn_queue.learn_queue()
    await queue.put(job)
    writer = asyncio.create_task(learn_queue.run_learn_consumer())

    try:
        await asyncio.wait_for(queue.join(), timeout=2.0)
        assert attempts == 1101
        assert persisted == [job]
        assert delays
        assert max(delays) <= learn_queue._OUTBOX_RETRY_MAX_SEC
    finally:
        writer.cancel()
        await asyncio.gather(writer, return_exceptions=True)
        learn_queue.clear_repeater_learn_runtime_state()


@pytest.mark.asyncio
async def test_repeater_shutdown_discards_buffer_when_writer_never_started() -> None:
    from packages.repeater import learn_queue
    from pallas.core.platform.work_jobs.models import WorkJob

    learn_queue.clear_repeater_learn_runtime_state()
    learn_queue.learn_queue().put_nowait(
        WorkJob.create(kind="repeater.learn", payload={}, idempotency_key="repeater:shutdown")
    )

    await learn_queue.stop_repeater_learn_worker()

    assert learn_queue.learn_queue().empty()


@pytest.mark.asyncio
async def test_repeater_starts_one_outbox_writer_per_effective_concurrency(monkeypatch: pytest.MonkeyPatch) -> None:
    from packages.repeater import learn_queue

    learn_queue.clear_repeater_learn_runtime_state()
    await learn_queue.stop_repeater_learn_worker()
    monkeypatch.setattr(learn_queue, "learn_concurrency", lambda: 3)

    await learn_queue.start_repeater_learn_worker()
    try:
        assert len(learn_queue._worker_tasks) == 3
    finally:
        await learn_queue.stop_repeater_learn_worker()


@pytest.mark.asyncio
async def test_repeater_work_handler_processes_serialized_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    from packages.repeater.work_handler import handle_repeater_learn

    process = AsyncMock()
    monkeypatch.setattr("packages.repeater.learner.Learner.process_work_payload", process)

    await handle_repeater_learn({
        "chat": {
            "group_id": 42,
            "user_id": 11,
            "bot_id": 100,
            "raw_message": "这一句",
            "plain_text": "这一句",
            "time": 20,
        },
        "predecessor": None,
    })

    process.assert_awaited_once()


def test_repeater_work_handlers_include_image_cache_capture() -> None:
    from packages.repeater.work_handler import repeater_work_handlers

    assert "image_cache.capture" in repeater_work_handlers()
    assert "sticker_vision.select" in repeater_work_handlers()
    assert "group.insight" in repeater_work_handlers()
    assert "sticker.label.visual" in repeater_work_handlers()
