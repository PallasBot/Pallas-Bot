from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest


@pytest.fixture(autouse=True)
def reset_capture_log_throttle(monkeypatch: pytest.MonkeyPatch) -> None:
    from pallas.core.foundation.logging import throttle

    monkeypatch.setattr(throttle, "_LAST_EMIT_AT", {})


@pytest.mark.asyncio
async def test_insert_image_buffers_durable_capture_job_under_ingress_pressure(monkeypatch: pytest.MonkeyPatch) -> None:
    from pallas.core.shared.utils import media_cache as mod

    await mod.reset_image_cache_runtime_state_for_tests()
    seg = SimpleNamespace(data={"url": "https://example.com/x.png"})
    monkeypatch.setattr(mod, "normalize_image_cq_code", lambda _seg: "[CQ:image,file=x.image]")

    await mod.insert_image(seg, bot_id=100, group_id=42, message_id=99)

    job = mod.image_capture_queue().get_nowait()
    assert job.kind == "image_cache.capture"
    assert job.idempotency_key.startswith("image_cache.capture:100:42:99:")
    assert job.payload["cq_code"] == "[CQ:image,file=x.image]"
    assert job.payload["url"] == "https://example.com/x.png"
    assert float(job.payload["created_at"] or 0) > 0

    await mod.reset_image_cache_runtime_state_for_tests()


def test_image_capture_payload_rejects_query_parameters_in_hostname(monkeypatch: pytest.MonkeyPatch) -> None:
    from pallas.core.shared.utils import media_cache as mod

    seg = SimpleNamespace(data={"url": "https://multimedia.nt.qq.com.cn&rkey=invalid"})
    monkeypatch.setattr(mod, "normalize_image_cq_code", lambda _seg: "[CQ:image,file=x.image]")

    assert mod.image_capture_payload(seg) is None


@pytest.mark.asyncio
async def test_image_capture_consumer_persists_buffered_jobs(monkeypatch: pytest.MonkeyPatch) -> None:
    from pallas.core.platform.work_jobs.models import WorkJob
    from pallas.core.shared.utils import media_cache as mod

    await mod.reset_image_cache_runtime_state_for_tests()
    store = SimpleNamespace(enqueue_many=AsyncMock())
    monkeypatch.setattr(mod, "build_work_job_store", lambda: store)
    job = WorkJob.create(
        kind="image_cache.capture",
        payload={"cq_code": "[CQ:image,file=x.image]", "url": "https://example.com/x.png"},
        idempotency_key="image_cache.capture:100:42:99:x",
    )

    await mod.image_capture_queue().put(job)
    task = asyncio.create_task(mod.run_image_capture_consumer())
    try:
        for _ in range(20):
            if store.enqueue_many.await_count:
                break
            await asyncio.sleep(0.01)
        store.enqueue_many.assert_awaited_once_with([job])
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        await mod.reset_image_cache_runtime_state_for_tests()


@pytest.mark.asyncio
async def test_image_capture_consumer_isolates_poison_job_and_keeps_good_jobs(monkeypatch: pytest.MonkeyPatch) -> None:
    from pallas.core.platform.work_jobs.models import InvalidWorkJobPayloadError, WorkJob
    from pallas.core.shared.utils import media_cache as mod

    await mod.reset_image_cache_runtime_state_for_tests()
    bad = WorkJob.create(
        kind="image_cache.capture",
        payload={"bad\x00": "PAYLOAD_SENTINEL", "bad": "collision"},
        idempotency_key="image:bad",
    )
    good = WorkJob.create(
        kind="image_cache.capture",
        payload={"cq_code": "[CQ:image,file=good.image]", "url": "https://example.com/good.png"},
        idempotency_key="image:good",
    )
    persisted: list[WorkJob] = []
    warnings: list[str] = []

    class Store:
        async def enqueue_many(self, jobs: list[WorkJob]) -> None:
            for job in jobs:
                if job.idempotency_key == "image:bad":
                    raise InvalidWorkJobPayloadError("payload contains PAYLOAD_SENTINEL")
            persisted.extend(jobs)

    monkeypatch.setattr(mod, "build_work_job_store", Store)
    monkeypatch.setattr(mod.logger, "warning", lambda *args: warnings.append(" ".join(map(str, args))))
    await mod.image_capture_queue().put(bad)
    await mod.image_capture_queue().put(good)
    task = asyncio.create_task(mod.run_image_capture_consumer())
    try:
        await asyncio.wait_for(mod.image_capture_queue().join(), timeout=0.5)
        assert persisted == [good]
        assert warnings
        assert "PAYLOAD_SENTINEL" not in " ".join(warnings)
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        await mod.reset_image_cache_runtime_state_for_tests()


@pytest.mark.asyncio
async def test_image_capture_consumer_backs_off_transient_failures_and_cancels_cleanly(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from pallas.core.platform.work_jobs.models import WorkJob
    from pallas.core.shared.utils import media_cache as mod

    await mod.reset_image_cache_runtime_state_for_tests()
    attempts = 0
    persisted: list[WorkJob] = []
    warnings: list[str] = []

    class Store:
        async def enqueue_many(self, jobs: list[WorkJob]) -> None:
            nonlocal attempts
            attempts += 1
            if attempts < 3:
                raise RuntimeError("SQL params contain PAYLOAD_SENTINEL")
            persisted.extend(jobs)

    job = WorkJob.create(
        kind="image_cache.capture",
        payload={"cq_code": "[CQ:image,file=retry.image]", "url": "https://example.com/retry.png"},
        idempotency_key="image:retry",
    )
    monkeypatch.setattr(mod, "build_work_job_store", Store)
    monkeypatch.setattr(mod, "_IMAGE_CAPTURE_RETRY_BASE_SEC", 0.02, raising=False)
    monkeypatch.setattr(mod.logger, "warning", lambda *args: warnings.append(" ".join(map(str, args))))
    await mod.image_capture_queue().put(job)
    task = asyncio.create_task(mod.run_image_capture_consumer())
    try:
        await asyncio.sleep(0.005)
        assert attempts == 1
        await asyncio.wait_for(mod.image_capture_queue().join(), timeout=0.5)
        assert persisted == [job]
        assert attempts == 3
        assert len(warnings) == 1
        assert "PAYLOAD_SENTINEL" not in " ".join(warnings)
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        await mod.reset_image_cache_runtime_state_for_tests()


@pytest.mark.asyncio
async def test_image_capture_consumer_isolates_permanent_failure_after_transient_retry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from pallas.core.platform.work_jobs.models import InvalidWorkJobPayloadError, WorkJob, normalize_work_job_payload
    from pallas.core.shared.utils import media_cache as mod

    await mod.reset_image_cache_runtime_state_for_tests()
    attempts = 0
    persisted: list[WorkJob] = []
    warnings: list[str] = []
    bad = WorkJob.create(
        kind="image_cache.capture",
        payload={"cq_code": "[CQ:image,file=bad.image]", "url": "https://example.com/bad.png"},
        idempotency_key="image:transient-then-invalid",
    )
    good = WorkJob.create(
        kind="image_cache.capture",
        payload={"cq_code": "[CQ:image,file=good.image]", "url": "https://example.com/good.png"},
        idempotency_key="image:transient-then-good",
    )

    class Store:
        async def enqueue_many(self, jobs: list[WorkJob]) -> None:
            nonlocal attempts
            attempts += 1
            if attempts == 1:
                jobs[0].payload.update({"bad\x00": "PAYLOAD_SENTINEL", "bad": "collision"})
                raise RuntimeError("temporary database outage")
            for job in jobs:
                try:
                    normalize_work_job_payload(job.payload)
                except InvalidWorkJobPayloadError as exc:
                    raise InvalidWorkJobPayloadError(f"{exc} PAYLOAD_SENTINEL") from exc
            persisted.extend(jobs)

    monkeypatch.setattr(mod, "build_work_job_store", Store)
    monkeypatch.setattr(mod, "_IMAGE_CAPTURE_RETRY_BASE_SEC", 0.01, raising=False)
    monkeypatch.setattr(mod.logger, "warning", lambda *args: warnings.append(" ".join(map(str, args))))
    await mod.image_capture_queue().put(bad)
    await mod.image_capture_queue().put(good)
    task = asyncio.create_task(mod.run_image_capture_consumer())
    try:
        await asyncio.wait_for(mod.image_capture_queue().join(), timeout=0.5)
        assert attempts == 3
        assert persisted == [good]
        assert warnings
        assert "PAYLOAD_SENTINEL" not in " ".join(warnings)
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        await mod.reset_image_cache_runtime_state_for_tests()


@pytest.mark.asyncio
async def test_image_capture_consumer_cancellation_finishes_queue_accounting(monkeypatch: pytest.MonkeyPatch) -> None:
    from pallas.core.platform.work_jobs.models import WorkJob
    from pallas.core.shared.utils import media_cache as mod

    await mod.reset_image_cache_runtime_state_for_tests()
    attempted = asyncio.Event()

    class Store:
        async def enqueue_many(self, _jobs: list[WorkJob]) -> None:
            attempted.set()
            raise RuntimeError("temporary database outage")

    monkeypatch.setattr(mod, "build_work_job_store", Store)
    monkeypatch.setattr(mod, "_IMAGE_CAPTURE_RETRY_BASE_SEC", 60.0, raising=False)
    await mod.image_capture_queue().put(
        WorkJob.create(
            kind="image_cache.capture",
            payload={"cq_code": "[CQ:image,file=shutdown.image]", "url": "https://example.com/shutdown.png"},
            idempotency_key="image:shutdown",
        )
    )
    queue = mod.image_capture_queue()
    task = asyncio.create_task(mod.run_image_capture_consumer())
    try:
        await attempted.wait()
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        await asyncio.wait_for(queue.join(), timeout=0.1)
        assert queue._unfinished_tasks == 0
    finally:
        if not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        await mod.reset_image_cache_runtime_state_for_tests()


@pytest.mark.asyncio
async def test_image_capture_backoff_stays_capped_after_prolonged_outage(monkeypatch: pytest.MonkeyPatch) -> None:
    from pallas.core.platform.work_jobs.models import WorkJob
    from pallas.core.shared.utils import media_cache as mod

    await mod.reset_image_cache_runtime_state_for_tests()
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

    monkeypatch.setattr(mod, "build_work_job_store", Store)
    monkeypatch.setattr(mod.asyncio, "sleep", fast_sleep)
    job = WorkJob.create(kind="image_cache.capture", payload={}, idempotency_key="image:long-outage")
    queue = mod.image_capture_queue()
    await queue.put(job)
    task = asyncio.create_task(mod.run_image_capture_consumer())
    try:
        await asyncio.wait_for(queue.join(), timeout=2.0)
        assert persisted == [job]
        assert delays
        assert max(delays) <= mod._IMAGE_CAPTURE_RETRY_MAX_SEC
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        await mod.reset_image_cache_runtime_state_for_tests()


@pytest.mark.asyncio
async def test_image_capture_work_handler_rejects_non_http_url() -> None:
    from pallas.core.shared.utils import media_cache as mod

    with pytest.raises(ValueError, match="http"):
        await mod.handle_image_cache_capture({"cq_code": "[CQ:image,file=x.image]", "url": "file:///tmp/x.png"})


@pytest.mark.asyncio
async def test_image_capture_work_handler_rejects_malformed_http_url() -> None:
    from pallas.core.shared.utils import media_cache as mod

    with pytest.raises(ValueError, match="valid http"):
        await mod.handle_image_cache_capture({
            "cq_code": "[CQ:image,file=x.image]",
            "url": "https://multimedia.nt.qq.com.cn&rkey=invalid",
        })


@pytest.mark.asyncio
async def test_image_capture_work_handler_does_not_retry_http_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    from pallas.core.shared.utils import media_cache as mod

    repo = SimpleNamespace(find_by_cq_code=AsyncMock(return_value=None), insert=AsyncMock())
    monkeypatch.setattr(mod, "image_cache_repo", repo)
    status = 400

    async def fake_fetch(_url: str) -> tuple[None, int]:
        return None, status

    monkeypatch.setattr(mod, "_fetch_image_bytes", fake_fetch)

    await mod.handle_image_cache_capture({
        "cq_code": "[CQ:image,file=expired.image]",
        "url": "https://multimedia.nt.qq.com.cn/download?file=expired",
    })

    repo.insert.assert_not_awaited()


@pytest.mark.asyncio
async def test_image_capture_work_handler_drops_expired_job_before_fetch(monkeypatch: pytest.MonkeyPatch) -> None:
    from types import SimpleNamespace

    from pallas.core.shared.utils import media_cache as mod

    now = 2_000_000_000.0
    repo = SimpleNamespace(find_by_cq_code=AsyncMock(), insert=AsyncMock())
    fetch = AsyncMock()
    monkeypatch.setattr(mod, "time", SimpleNamespace(time=lambda: now))
    monkeypatch.setattr(mod, "image_cache_repo", repo)
    monkeypatch.setattr(mod, "_fetch_image_bytes", fetch)

    await mod.handle_image_cache_capture({
        "cq_code": "[CQ:image,file=expired.image]",
        "url": "https://example.com/expired.png",
        "created_at": now - mod._IMAGE_CAPTURE_MAX_AGE_SEC - 1,
    })

    repo.find_by_cq_code.assert_not_awaited()
    fetch.assert_not_awaited()
    repo.insert.assert_not_awaited()


@pytest.mark.asyncio
async def test_image_capture_work_handler_times_out_hung_download(monkeypatch: pytest.MonkeyPatch) -> None:
    from pallas.core.shared.utils import media_cache as mod

    repo = SimpleNamespace(find_by_cq_code=AsyncMock(return_value=None), insert=AsyncMock())
    monkeypatch.setattr(mod, "image_cache_repo", repo)

    async def hang(_url: str):
        await asyncio.Event().wait()

    monkeypatch.setattr(mod, "_fetch_image_bytes", hang)
    monkeypatch.setattr(mod, "_IMAGE_CAPTURE_DOWNLOAD_BUDGET_SEC", 0.01)

    await mod.handle_image_cache_capture({
        "cq_code": "[CQ:image,file=hang.image]",
        "url": "https://multimedia.nt.qq.com.cn/download?file=hang",
    })

    repo.insert.assert_not_awaited()


@pytest.mark.asyncio
async def test_insert_image_io_uses_detached_model_for_postgresql(monkeypatch: pytest.MonkeyPatch) -> None:
    from pallas.core.shared.utils import media_cache as mod

    inserted: list[object] = []

    class FakeRepository:
        async def find_by_cq_code(self, _cq_code):
            return None

        async def insert(self, cache):
            inserted.append(cache)

    async def fake_fetch(_url: str) -> tuple[bytes, int]:
        return b"image", 200

    monkeypatch.setattr(mod, "image_cache_repo", FakeRepository())
    monkeypatch.setattr(mod, "is_postgresql_backend", lambda: True, raising=False)
    monkeypatch.setattr(mod, "_fetch_image_bytes", fake_fetch)

    await mod.handle_image_cache_capture({
        "cq_code": "[CQ:image,file=x.image]",
        "url": "https://example.com/image.png",
    })

    assert len(inserted) == 1
    assert inserted[0].blob_data == b"image"


@pytest.mark.asyncio
async def test_image_cache_hit_touches_metadata_without_rewriting_blob(monkeypatch: pytest.MonkeyPatch) -> None:
    from pallas.core.shared.utils import media_cache as mod

    existing = SimpleNamespace(blob_data=b"large-image", ref_times=1, date=20260101)
    repo = SimpleNamespace(
        find_by_cq_code=AsyncMock(return_value=existing),
        touch=AsyncMock(),
        save=AsyncMock(),
    )
    monkeypatch.setattr(mod, "image_cache_repo", repo)

    await mod.handle_image_cache_capture({
        "cq_code": "[CQ:image,file=existing.image]",
        "url": "https://example.com/image.png",
    })

    repo.touch.assert_awaited_once()
    assert repo.touch.await_args.args[0] == "[CQ:image,file=existing.image]"
    repo.save.assert_not_awaited()


@pytest.mark.asyncio
async def test_get_image_by_url_escapes_html_entities_before_query(monkeypatch: pytest.MonkeyPatch) -> None:
    from pallas.core.shared.utils import media_cache as mod

    cached = SimpleNamespace(blob_data=b"image-bytes")
    repo = SimpleNamespace(find_by_url=AsyncMock(return_value=cached))
    monkeypatch.setattr(mod, "image_cache_repo", repo)

    data = await mod.get_image_by_url("https://multimedia.nt.qq.com.cn/download?appid=1&rkey=x")

    assert data == b"image-bytes"
    called_url = repo.find_by_url.await_args.args[0]
    assert called_url == "https://multimedia.nt.qq.com.cn/download?appid=1&amp;rkey=x"


@pytest.mark.asyncio
async def test_get_image_by_url_miss_returns_none(monkeypatch: pytest.MonkeyPatch) -> None:
    from pallas.core.shared.utils import media_cache as mod

    repo = SimpleNamespace(find_by_url=AsyncMock(return_value=None))
    monkeypatch.setattr(mod, "image_cache_repo", repo)

    assert await mod.get_image_by_url("https://example.com/x.png") is None


@pytest.mark.asyncio
async def test_prune_image_cache_uses_default_retention_policy(monkeypatch: pytest.MonkeyPatch) -> None:
    from pallas.core.shared.utils import media_cache as mod

    prune = AsyncMock(return_value=SimpleNamespace(deleted_rows=0, deleted_blob_bytes=0, remaining_blob_bytes=0))
    monkeypatch.setattr(mod.image_cache_repo, "prune", prune, raising=False)

    await mod.prune_image_cache(today=__import__("datetime").date(2026, 8, 10))

    policy = prune.await_args.args[0]
    assert policy.single_use_before == 20260711
    assert policy.absolute_before == 20260512
    assert policy.max_blob_bytes == 20 * 1024**3
    assert policy.batch_size == 1000
