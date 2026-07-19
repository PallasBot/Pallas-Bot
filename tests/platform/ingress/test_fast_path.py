from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from nonebot.adapters.onebot.v11 import GroupMessageEvent, Message
from nonebot.exception import IgnoredException

from pallas.core.platform.ingress.fast_path import ingress_once_claim_safe_before_host_gates
from pallas.core.platform.shard.registry import config as shard_cfg


def test_ingress_once_claim_safe_when_no_host_gate(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "pallas.core.platform.ingress.fast_path.needs_group_host_bot_gate",
        lambda: False,
    )
    assert ingress_once_claim_safe_before_host_gates(1, "hello", at_fleet_bot=False) is True


def test_ingress_once_claim_unsafe_when_spy_live(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "pallas.core.platform.ingress.fast_path.needs_group_host_bot_gate",
        lambda: True,
    )
    monkeypatch.setattr(
        "pallas.core.platform.ingress.fast_path.loaded_hosted_activity_specs",
        lambda: (),
    )
    monkeypatch.setattr(
        "pallas.core.platform.ingress.fast_path.read_owned_gate_bot_id_sync",
        lambda _plugin, _gid: None,
    )
    monkeypatch.setattr(
        "pallas.core.platform.ingress.fast_path.hosted_activity_live",
        lambda **kwargs: True,
    )
    monkeypatch.setattr(
        "pallas.core.platform.ingress.fast_path.spec_matches_in_room_command",
        lambda _spec, _plain: True,
    )
    monkeypatch.setattr(
        "pallas.core.platform.ingress.fast_path.spec_matches_speak_traffic",
        lambda *_args, **_kwargs: False,
    )
    from types import SimpleNamespace

    spec = SimpleNamespace(
        activity_namespace="spy",
        plugin_key="who_is_spy",
        always_pass_prefixes=(),
    )
    monkeypatch.setattr(
        "pallas.core.platform.ingress.fast_path.loaded_hosted_activity_specs",
        lambda: (spec,),
    )
    assert ingress_once_claim_safe_before_host_gates(1, "牛牛卧底", at_fleet_bot=False) is False


@pytest.mark.asyncio
async def test_unified_ingress_early_once_claim_before_host_checks(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(shard_cfg, "is_sharding_active", lambda: False)
    monkeypatch.setattr("pallas.core.platform.ingress.gate.ingress_gate_active", lambda: True)
    monkeypatch.setattr("pallas.core.platform.ingress.gate.fleet_bot_ids_contains", lambda _uid: False)
    monkeypatch.setattr("pallas.core.platform.ingress.gate.ingress_fanout_bypasses_claim", lambda _plain: False)
    monkeypatch.setattr(
        "pallas.core.platform.ingress.gate.ingress_once_claim_safe_before_host_gates",
        lambda *_args, **_kwargs: True,
    )
    hosted = MagicMock(return_value=True)
    dream = AsyncMock(return_value=True)
    monkeypatch.setattr("pallas.core.platform.ingress.gate.hosted_activity_ingress_passes", hosted)
    monkeypatch.setattr("pallas.core.platform.ingress.gate.dream_session_ingress_passes", dream)
    monkeypatch.setattr(
        "pallas.core.platform.ingress.gate.claim_federate_group_message_ingress",
        AsyncMock(return_value=True),
    )
    from pallas.core.platform.ingress.gate import ingress_group_message_gate

    class FakeBot:
        def __init__(self, self_id: int) -> None:
            self.self_id = str(self_id)

    event = GroupMessageEvent.model_construct(
        time=100,
        self_id=111,
        post_type="message",
        message_type="group",
        sub_type="normal",
        user_id=999,
        group_id=12345,
        message_id=1,
        message=Message("热路径"),
        raw_message="热路径",
    )

    await ingress_group_message_gate(FakeBot(111), event)
    hosted.assert_called()
    dream.assert_called()

    hosted.reset_mock()
    dream.reset_mock()
    with pytest.raises(IgnoredException):
        await ingress_group_message_gate(FakeBot(222), event)
    hosted.assert_not_called()
    dream.assert_not_called()
