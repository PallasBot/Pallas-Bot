from __future__ import annotations

from unittest.mock import patch

from pallas.core.platform.multi_bot.dedup import needs_group_host_bot_gate


def test_needs_group_host_bot_gate_single_bot() -> None:
    with (
        patch("pallas.core.platform.shard.context.sharding_active", return_value=False),
        patch("nonebot.get_bots", return_value={"123": object()}),
    ):
        assert needs_group_host_bot_gate() is False


def test_needs_group_host_bot_gate_multi_bot_same_process() -> None:
    with (
        patch("pallas.core.platform.shard.context.sharding_active", return_value=False),
        patch("nonebot.get_bots", return_value={"1": object(), "2": object()}),
    ):
        assert needs_group_host_bot_gate() is True


def test_needs_group_host_bot_gate_sharded_single_bot() -> None:
    with (
        patch("pallas.core.platform.shard.context.sharding_active", return_value=True),
        patch("nonebot.get_bots", return_value={"123": object()}),
    ):
        assert needs_group_host_bot_gate() is True
