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
async def test_image_capture_work_handler_times_out_hung_download(monkeypatch: pytest.MonkeyPatch) -> None:
    from pallas.core.shared.utils import media_cache as mod

    repo = SimpleNamespace(find_by_cq_code=AsyncMock(return_value=None), insert=AsyncMock())
    monkeypatch.setattr(mod, "image_cache_repo", repo)

    async def hang(_url: str):
        await asyncio.Event().wait()

    monkeypatch.setattr(mod, "_fetch_image_bytes", hang)

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
