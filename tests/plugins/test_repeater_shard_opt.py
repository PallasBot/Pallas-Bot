from __future__ import annotations

import pytest

from packages.repeater.shard_opt import (
    local_connected_bot_ids,
    repeater_maintenance_runs_on_worker,
    repeater_scheduler_runs_on_worker,
    repeater_worker_handles_message,
)


@pytest.mark.asyncio
async def test_repeater_fanout_enabled_for_group_requires_two_bots(monkeypatch):
    from packages.repeater import fanout_reply

    monkeypatch.setattr(
        "pallas.core.platform.shard.context.sharding_active",
        lambda: True,
    )
    monkeypatch.setattr(
        fanout_reply,
        "get_repeater_config",
        lambda: type("C", (), {"fanout_enabled": True})(),
    )

    async def one(_gid: int) -> int:
        return 1

    monkeypatch.setattr(fanout_reply, "count_fanout_capable_bots", one)
    assert await fanout_reply.repeater_fanout_enabled_for_group(1) is False

    async def two(_gid: int) -> int:
        return 2

    monkeypatch.setattr(fanout_reply, "count_fanout_capable_bots", two)
    assert await fanout_reply.repeater_fanout_enabled_for_group(1) is True


def test_repeater_worker_handles_unified(monkeypatch):
    monkeypatch.setattr(
        "pallas.core.platform.shard.registry.config.is_sharding_active",
        lambda: False,
    )
    assert repeater_worker_handles_message(999) is True


def test_repeater_worker_handles_all_local_bots_when_sharded_without_fanout(monkeypatch):
    monkeypatch.setattr(
        "pallas.core.platform.shard.registry.config.is_sharding_active",
        lambda: True,
    )
    monkeypatch.setattr(
        "packages.repeater.config.get_repeater_config",
        lambda: type("C", (), {"fanout_enabled": False})(),
    )
    monkeypatch.setattr(
        "pallas.core.platform.shard.local_representative.is_local_worker_representative",
        lambda bid: bid == 100,
    )
    assert repeater_worker_handles_message(100) is True
    assert repeater_worker_handles_message(200) is True


def test_repeater_worker_handles_all_local_bots_when_fanout_enabled(monkeypatch):
    monkeypatch.setattr(
        "pallas.core.platform.shard.registry.config.is_sharding_active",
        lambda: True,
    )
    monkeypatch.setattr(
        "packages.repeater.config.get_repeater_config",
        lambda: type("C", (), {"fanout_enabled": True})(),
    )
    monkeypatch.setattr(
        "pallas.core.platform.shard.local_representative.is_local_worker_representative",
        lambda bid: bid == 100,
    )
    assert repeater_worker_handles_message(100) is True
    assert repeater_worker_handles_message(200) is True


def test_scheduler_skips_worker_without_rep(monkeypatch):
    monkeypatch.setattr(
        "pallas.core.platform.shard.context.sharding_active",
        lambda: True,
    )
    monkeypatch.setattr(
        "pallas.core.platform.shard.context.local_representative_bot_id",
        lambda: None,
    )
    assert repeater_scheduler_runs_on_worker() is False


def test_maintenance_runs_only_on_shard_zero_when_sharded(monkeypatch):
    monkeypatch.setattr(
        "pallas.core.platform.shard.context.sharding_active",
        lambda: True,
    )
    monkeypatch.setattr(
        "pallas.core.platform.shard.context.shard_id",
        lambda: 0,
    )
    assert repeater_maintenance_runs_on_worker() is True

    monkeypatch.setattr(
        "pallas.core.platform.shard.context.shard_id",
        lambda: 3,
    )
    assert repeater_maintenance_runs_on_worker() is False


def test_maintenance_runs_when_not_sharded(monkeypatch):
    monkeypatch.setattr(
        "pallas.core.platform.shard.registry.config.is_sharding_active",
        lambda: False,
    )
    assert repeater_maintenance_runs_on_worker() is True


def test_local_connected_bot_ids_reads_nonebot(monkeypatch):
    monkeypatch.setattr(
        "nonebot.get_bots",
        lambda: {"1001": object(), "2002": object(), "bad": object()},
    )
    assert local_connected_bot_ids() == frozenset({1001, 2002})
