from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest


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
    assert job.payload == {
        "cq_code": "[CQ:image,file=x.image]",
        "url": "https://example.com/x.png",
    }

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
async def test_insert_image_io_uses_detached_model_for_postgresql(monkeypatch: pytest.MonkeyPatch) -> None:
    from pallas.core.shared.utils import media_cache as mod

    inserted: list[object] = []

    class FakeRepository:
        async def find_by_cq_code(self, _cq_code):
            return None

        async def insert(self, cache):
            inserted.append(cache)

    async def fake_get(_url):
        return SimpleNamespace(status_code=200, content=b"image")

    monkeypatch.setattr(mod, "image_cache_repo", FakeRepository())
    monkeypatch.setattr(mod, "is_postgresql_backend", lambda: True, raising=False)
    monkeypatch.setattr(mod.HTTPXClient, "get", fake_get)

    await mod.handle_image_cache_capture({
        "cq_code": "[CQ:image,file=x.image]",
        "url": "https://example.com/image.png",
    })

    assert len(inserted) == 1
    assert inserted[0].blob_data == b"image"
