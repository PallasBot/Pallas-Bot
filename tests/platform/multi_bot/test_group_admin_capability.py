from __future__ import annotations

import asyncio

import pytest

from pallas.core.platform.multi_bot import group_admin_capability as capability


@pytest.fixture(autouse=True)
def reset_capability_cache() -> None:
    capability.clear_group_admin_capability_cache()


@pytest.mark.asyncio
async def test_resolve_group_admin_capability_caches_successful_lookup() -> None:
    calls = 0

    async def fetch_role(group_id: int, bot_id: int) -> str:
        nonlocal calls
        calls += 1
        assert (group_id, bot_id) == (1, 2)
        return "admin"

    assert await capability.resolve_group_admin_capability(1, 2, fetch_role=fetch_role) is True
    assert await capability.resolve_group_admin_capability(1, 2, fetch_role=fetch_role) is True
    assert calls == 1


@pytest.mark.asyncio
async def test_concurrent_role_queries_share_one_lookup() -> None:
    calls = 0
    started = asyncio.Event()
    release = asyncio.Event()

    async def fetch_role(group_id: int, bot_id: int) -> str:
        nonlocal calls
        calls += 1
        started.set()
        await release.wait()
        return "owner"

    tasks = [
        asyncio.create_task(capability.resolve_group_admin_capability(1, 2, fetch_role=fetch_role)) for _ in range(3)
    ]
    await started.wait()
    release.set()

    assert await asyncio.gather(*tasks) == [True, True, True]
    assert calls == 1


def test_admin_notice_updates_cached_capability() -> None:
    capability.record_group_admin_notice(group_id=1, bot_id=2, role="admin")
    assert capability.local_group_admin_bot_ids(1) == frozenset({2})

    capability.record_group_admin_notice(group_id=1, bot_id=2, role="member")
    assert capability.local_group_admin_bot_ids(1) == frozenset()


@pytest.mark.asyncio
async def test_capacity_eviction_queries_an_evicted_pair_again() -> None:
    calls = 0

    async def fetch_role(_group_id: int, _bot_id: int) -> str:
        nonlocal calls
        calls += 1
        return "admin"

    capability.set_group_admin_capability_cache_capacity(1)
    await capability.resolve_group_admin_capability(1, 2, fetch_role=fetch_role)
    await capability.resolve_group_admin_capability(1, 3, fetch_role=fetch_role)
    await capability.resolve_group_admin_capability(1, 2, fetch_role=fetch_role)

    assert calls == 3


@pytest.mark.asyncio
async def test_failed_lookup_is_unknown_and_does_not_mark_complete() -> None:
    calls = 0

    async def fetch_role(_group_id: int, _bot_id: int) -> str:
        nonlocal calls
        calls += 1
        raise RuntimeError("member API unavailable")

    assert await capability.resolve_group_admin_capability(1, 2, fetch_role=fetch_role) is None
    assert capability.local_group_admin_observation_complete(1, {2}) is False
    assert await capability.resolve_group_admin_capability(1, 2, fetch_role=fetch_role) is None
    assert calls == 2
