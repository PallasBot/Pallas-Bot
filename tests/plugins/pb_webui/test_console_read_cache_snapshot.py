from __future__ import annotations

import asyncio

import pytest

from packages.pb_webui.console_read_cache import cached_read, clear_extended_read_cache, drop_read_cache


@pytest.mark.asyncio
async def test_swr_first_load_awaits_and_dedups_concurrent(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("PALLAS_DATA_DIR", str(tmp_path))
    clear_extended_read_cache()
    gate = asyncio.Event()
    calls = 0

    async def loader() -> str:
        nonlocal calls
        calls += 1
        await gate.wait()
        return "done"

    try:
        t1 = asyncio.create_task(cached_read(key="cc-k", loader=loader, ttl_sec=60, stale_sec=300, swr=True))
        t2 = asyncio.create_task(cached_read(key="cc-k", loader=loader, ttl_sec=60, stale_sec=300, swr=True))
        await asyncio.sleep(0.05)
        assert calls == 1
        gate.set()
        r1, r2 = await asyncio.gather(t1, t2)
        assert r1 == r2 == "done"
    finally:
        gate.set()
        clear_extended_read_cache()


@pytest.mark.asyncio
async def test_swr_serves_stale_then_refreshes_in_background(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("PALLAS_DATA_DIR", str(tmp_path))
    clear_extended_read_cache()
    gate = asyncio.Event()
    calls = 0

    async def loader() -> str:
        nonlocal calls
        calls += 1
        if calls == 2:
            await gate.wait()
        return f"value-{calls}"

    try:
        await cached_read(key="swr-k", loader=loader, ttl_sec=0.01, stale_sec=5.0, swr=True)
        await asyncio.sleep(0.03)
        v2 = await cached_read(key="swr-k", loader=loader, ttl_sec=0.01, stale_sec=5.0, swr=True)
        assert v2 == "value-1"
        assert calls == 2
        gate.set()
        await asyncio.sleep(0.05)
        v3 = await cached_read(key="swr-k", loader=loader, ttl_sec=0.01, stale_sec=5.0, swr=True)
        assert v3 == "value-2"
    finally:
        gate.set()
        clear_extended_read_cache()


@pytest.mark.asyncio
async def test_swr_refresh_failure_keeps_stale(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("PALLAS_DATA_DIR", str(tmp_path))
    clear_extended_read_cache()
    calls = 0

    async def loader() -> str:
        nonlocal calls
        calls += 1
        if calls == 1:
            return "good"
        raise RuntimeError("boom")

    try:
        assert await cached_read(key="fail-k", loader=loader, ttl_sec=0.01, stale_sec=5.0, swr=True) == "good"
        await asyncio.sleep(0.03)
        assert await cached_read(key="fail-k", loader=loader, ttl_sec=0.01, stale_sec=5.0, swr=True) == "good"
        await asyncio.sleep(0.05)
        assert await cached_read(key="fail-k", loader=loader, ttl_sec=0.01, stale_sec=5.0, swr=True) == "good"
    finally:
        clear_extended_read_cache()


@pytest.mark.asyncio
async def test_snapshot_persists_across_cache_clear(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("PALLAS_DATA_DIR", str(tmp_path))
    clear_extended_read_cache()
    calls = 0

    async def loader() -> dict[str, int]:
        nonlocal calls
        calls += 1
        return {"n": calls}

    try:
        assert await cached_read(
            key="snap-k", loader=loader, ttl_sec=60, stale_sec=300, swr=True, persist_snapshot=True
        ) == {"n": 1}
        clear_extended_read_cache()
        v2 = await cached_read(key="snap-k", loader=loader, ttl_sec=60, stale_sec=300, swr=True, persist_snapshot=True)
        assert v2 == {"n": 1}
    finally:
        clear_extended_read_cache()


@pytest.mark.asyncio
async def test_drop_read_cache_removes_memory_and_snapshot(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("PALLAS_DATA_DIR", str(tmp_path))
    clear_extended_read_cache()
    calls = 0

    async def loader() -> dict[str, int]:
        nonlocal calls
        calls += 1
        return {"n": calls}

    try:
        await cached_read(key="drop-k", loader=loader, ttl_sec=60, stale_sec=300, swr=True, persist_snapshot=True)
        assert calls == 1
        drop_read_cache(("drop-k",))
        v = await cached_read(key="drop-k", loader=loader, ttl_sec=60, stale_sec=300, swr=True, persist_snapshot=True)
        assert v == {"n": 2}
        assert calls == 2
    finally:
        clear_extended_read_cache()
