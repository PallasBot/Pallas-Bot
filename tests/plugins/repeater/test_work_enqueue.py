from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest


@pytest.mark.asyncio
async def test_enqueue_repeater_learn_captures_idempotent_work_job(monkeypatch: pytest.MonkeyPatch) -> None:
    from packages.repeater import learn_queue
    from pallas.core.platform.ingress import hotpath_metrics

    payload = SimpleNamespace(to_dict=lambda: {"chat": {"group_id": 42}})
    chat = SimpleNamespace(chat_data=SimpleNamespace(group_id=42, bot_id=100))
    event = SimpleNamespace(group_id=42, message_id=99, self_id=100)
    monkeypatch.setattr(learn_queue, "claim_group_message_event", AsyncMock(return_value=True))
    monkeypatch.setattr("packages.repeater.learner.Learner.capture_for_work", AsyncMock(return_value=payload))
    learn_queue.clear_repeater_learn_runtime_state()
    hotpath_metrics.clear_hotpath_metrics_for_tests()

    assert await learn_queue.enqueue_repeater_learn(chat, event) is True

    job = learn_queue.learn_queue().get_nowait()
    assert job.kind == "repeater.learn"
    assert job.idempotency_key == "repeater.learn:42:99:100"
    assert job.payload == {"chat": {"group_id": 42}}
    assert hotpath_metrics.hotpath_metrics_snapshot()["learn_enqueued"] == 1
    assert hotpath_metrics.hotpath_metrics_snapshot()["learn_buffered"] == 1


@pytest.mark.asyncio
async def test_enqueue_repeater_learn_buffers_job_without_waiting_for_outbox(monkeypatch: pytest.MonkeyPatch) -> None:
    from packages.repeater import learn_queue

    learn_queue.clear_repeater_learn_runtime_state()
    payload = SimpleNamespace(to_dict=lambda: {"chat": {"group_id": 42}})
    chat = SimpleNamespace(chat_data=SimpleNamespace(group_id=42, bot_id=100))
    event = SimpleNamespace(group_id=42, message_id=99, self_id=100)
    store = SimpleNamespace(enqueue_many=AsyncMock())
    monkeypatch.setattr(learn_queue, "claim_group_message_event", AsyncMock(return_value=True))
    monkeypatch.setattr("packages.repeater.learner.Learner.capture_for_work", AsyncMock(return_value=payload))
    monkeypatch.setattr(learn_queue, "build_work_job_store", lambda: store)

    assert await learn_queue.enqueue_repeater_learn(chat, event) is True

    store.enqueue_many.assert_not_awaited()
    assert learn_queue.learn_queue().qsize() == 1


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
async def test_repeater_outbox_writer_drops_nul_payload_without_retrying(monkeypatch: pytest.MonkeyPatch) -> None:
    from packages.repeater import learn_queue
    from pallas.core.platform.work_jobs.models import WorkJob

    learn_queue.clear_repeater_learn_runtime_state()
    store = SimpleNamespace(
        enqueue_many=AsyncMock(
            side_effect=RuntimeError("unsupported Unicode escape sequence: \\u0000 cannot be converted to text")
        )
    )
    monkeypatch.setattr(learn_queue, "build_work_job_store", lambda: store)
    monkeypatch.setattr(learn_queue, "wait_pg_pool_headroom_for_learn", AsyncMock())
    learn_queue.learn_queue().put_nowait(
        WorkJob.create(kind="repeater.learn", payload={"raw_message": "bad\\x00payload"}, idempotency_key="repeater:nul")
    )
    writer = asyncio.create_task(learn_queue.run_learn_consumer())

    try:
        for _ in range(20):
            if store.enqueue_many.await_count:
                break
            await asyncio.sleep(0.01)
        await asyncio.sleep(0.25)
        store.enqueue_many.assert_awaited_once()
    finally:
        writer.cancel()
        await asyncio.gather(writer, return_exceptions=True)


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
