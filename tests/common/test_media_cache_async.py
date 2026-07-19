from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest


@pytest.mark.asyncio
async def test_insert_image_only_enqueues_capture(monkeypatch: pytest.MonkeyPatch) -> None:
    from pallas.core.shared.utils import media_cache as mod

    await mod.reset_image_cache_runtime_state_for_tests()
    seg = SimpleNamespace(data={"url": "http://example.com/x.png"})

    called = False

    async def fake_insert_image_io(image_seg):
        nonlocal called
        called = True

    monkeypatch.setattr(mod, "_insert_image_io", fake_insert_image_io)

    await mod.insert_image(seg)

    assert mod.image_capture_queue().qsize() == 1
    assert called is False

    await mod.reset_image_cache_runtime_state_for_tests()


@pytest.mark.asyncio
async def test_image_capture_consumer_processes_queue(monkeypatch: pytest.MonkeyPatch) -> None:
    from pallas.core.shared.utils import media_cache as mod

    await mod.reset_image_cache_runtime_state_for_tests()
    seen: list[object] = []
    seg = SimpleNamespace(data={"url": "http://example.com/x.png"})

    async def fake_insert_image_io(image_seg):
        seen.append(image_seg)

    monkeypatch.setattr(mod, "_insert_image_io", fake_insert_image_io)

    await mod.image_capture_queue().put(seg)
    task = asyncio.create_task(mod.run_image_capture_consumer())
    try:
        await asyncio.wait_for(mod.image_capture_queue().join(), timeout=1.0)
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        await mod.reset_image_cache_runtime_state_for_tests()

    assert seen == [seg]
