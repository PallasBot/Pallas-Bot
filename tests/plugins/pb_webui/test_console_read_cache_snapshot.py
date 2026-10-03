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
async def test_cancelling_loader_owner_does_not_cancel_other_waiters(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("PALLAS_DATA_DIR", str(tmp_path))
    clear_extended_read_cache()
    loader_started = asyncio.Event()
    second_waiter_entered = asyncio.Event()
    loader_cancelled = asyncio.Event()
    release_loader = asyncio.Event()

    async def loader() -> dict[str, int]:
        loader_started.set()
        try:
            await release_loader.wait()
        except asyncio.CancelledError:
            loader_cancelled.set()
            raise
        return {"value": 1}

    async def second_waiter() -> dict[str, int]:
        second_waiter_entered.set()
        return await cached_read(key="cancel-k", loader=loader, ttl_sec=60)

    owner = asyncio.create_task(cached_read(key="cancel-k", loader=loader, ttl_sec=60))
    waiter = None
    try:
        await loader_started.wait()
        waiter = asyncio.create_task(second_waiter())
        await second_waiter_entered.wait()
        owner.cancel()
        with pytest.raises(asyncio.CancelledError):
            await owner
        assert not loader_cancelled.is_set()
        release_loader.set()
        assert await waiter == {"value": 1}
    finally:
        release_loader.set()
        await asyncio.gather(owner, *([waiter] if waiter is not None else []), return_exceptions=True)
        clear_extended_read_cache()


@pytest.mark.asyncio
async def test_concurrent_cache_waiters_receive_isolated_copies(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("PALLAS_DATA_DIR", str(tmp_path))
    clear_extended_read_cache()
    loader_started = asyncio.Event()
    waiter_entered = asyncio.Event()
    release_loader = asyncio.Event()

    async def loader() -> dict[str, list[int]]:
        loader_started.set()
        await release_loader.wait()
        return {"values": [1]}

    async def wait_for_value() -> dict[str, list[int]]:
        waiter_entered.set()
        return await cached_read(key="copy-k", loader=loader, ttl_sec=60)

    owner = asyncio.create_task(cached_read(key="copy-k", loader=loader, ttl_sec=60))
    waiter = None
    try:
        await loader_started.wait()
        waiter = asyncio.create_task(wait_for_value())
        await waiter_entered.wait()
        release_loader.set()
        first, second = await asyncio.gather(owner, waiter)
        first["values"].append(2)
        assert second == {"values": [1]}
        assert await cached_read(key="copy-k", loader=loader, ttl_sec=60) == {"values": [1]}
    finally:
        release_loader.set()
        await asyncio.gather(owner, *([waiter] if waiter is not None else []), return_exceptions=True)
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
async def test_swr_inflight_refresh_returns_fresh_value(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("PALLAS_DATA_DIR", str(tmp_path))
    clear_extended_read_cache()
    gate = asyncio.Event()
    calls = 0

    async def loader() -> str:
        nonlocal calls
        calls += 1
        if calls == 1:
            return "old"
        await gate.wait()
        return "fresh"

    try:
        assert await cached_read(key="infl-k", loader=loader, ttl_sec=0.01, stale_sec=5.0, swr=True) == "old"
        await asyncio.sleep(0.03)
        v2 = await cached_read(key="infl-k", loader=loader, ttl_sec=0.01, stale_sec=5.0, swr=True)
        assert v2 == "old"
        assert calls == 2
        t = asyncio.create_task(cached_read(key="infl-k", loader=loader, ttl_sec=0.01, stale_sec=5.0, swr=True))
        await asyncio.sleep(0.03)
        gate.set()
        assert await t == "fresh"
    finally:
        gate.set()
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
