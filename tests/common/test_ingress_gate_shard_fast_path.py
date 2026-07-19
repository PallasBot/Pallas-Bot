from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from nonebot.adapters.onebot.v11 import GroupMessageEvent, Message
from nonebot.exception import IgnoredException

from pallas.core.platform.ingress.claim_gate import IngressClaimError
from pallas.core.platform.shard.registry import config as shard_cfg


@pytest.mark.asyncio
async def test_shard_claim_lost_skips_host_gates(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(shard_cfg, "is_sharding_active", lambda: True)
    monkeypatch.setattr("pallas.core.platform.ingress.gate.shard_ctx.sharding_active", lambda: True)
    monkeypatch.setattr("pallas.core.platform.ingress.gate.ingress_gate_active", lambda: True)
    monkeypatch.setattr("pallas.core.platform.ingress.gate.fleet_bot_ids_contains", lambda _uid: False)
    monkeypatch.setattr("pallas.core.platform.ingress.gate.ingress_fanout_bypasses_claim", lambda _plain: False)
    monkeypatch.setattr(
        "pallas.core.platform.ingress.gate.ingress_once_claim_safe_before_host_gates",
        lambda *_a, **_k: True,
    )
    monkeypatch.setattr(
        "pallas.core.platform.ingress.gate.should_process_federate_group_on_current_deployment",
        lambda _gid: True,
    )
    host_gate = MagicMock(return_value=True)
    monkeypatch.setattr("pallas.core.platform.ingress.gate.hosted_activity_ingress_passes", host_gate)
    shard_claim = AsyncMock(side_effect=IngressClaimError("bot_claim_lost", message="lost", record_claim_lost=True))
    monkeypatch.setattr("pallas.core.platform.ingress.gate.run_ingress_message_claim", shard_claim)

    from pallas.core.platform.ingress.gate import ingress_group_message_gate

    class FakeBot:
        def __init__(self, self_id: int):
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
        message=Message("hello"),
        raw_message="hello",
    )

    with pytest.raises(IgnoredException):
        await ingress_group_message_gate(FakeBot(111), event)

    shard_claim.assert_awaited_once()
    host_gate.assert_not_called()


@pytest.mark.asyncio
async def test_shard_not_at_target_discards_before_host_gates(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(shard_cfg, "is_sharding_active", lambda: True)
    monkeypatch.setattr("pallas.core.platform.ingress.gate.shard_ctx.sharding_active", lambda: True)
    monkeypatch.setattr("pallas.core.platform.ingress.gate.ingress_gate_active", lambda: True)
    monkeypatch.setattr("pallas.core.platform.ingress.gate.fleet_bot_ids_contains", lambda _uid: False)
    monkeypatch.setattr("pallas.core.platform.ingress.gate.ingress_fanout_bypasses_claim", lambda _plain: False)
    monkeypatch.setattr(
        "pallas.core.platform.ingress.gate.should_process_federate_group_on_current_deployment",
        lambda _gid: True,
    )
    monkeypatch.setattr("pallas.core.platform.ingress.gate.pallas_at_targets", lambda _event: frozenset({222}))
    host_gate = MagicMock(return_value=True)
    monkeypatch.setattr("pallas.core.platform.ingress.gate.hosted_activity_ingress_passes", host_gate)
    shard_claim = AsyncMock(return_value=[])
    monkeypatch.setattr("pallas.core.platform.ingress.gate.run_ingress_message_claim", shard_claim)

    from pallas.core.platform.ingress.gate import ingress_group_message_gate

    class FakeBot:
        def __init__(self, self_id: int):
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
        message=Message("[CQ:at,qq=222] hi"),
        raw_message="[CQ:at,qq=222] hi",
    )

    with pytest.raises(IgnoredException):
        await ingress_group_message_gate(FakeBot(111), event)

    host_gate.assert_not_called()
    shard_claim.assert_not_awaited()
