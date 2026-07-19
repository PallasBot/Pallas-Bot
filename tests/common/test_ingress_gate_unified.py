from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from nonebot.adapters.onebot.v11 import GroupMessageEvent, Message
from nonebot.exception import IgnoredException

from pallas.core.platform.shard.registry import config as shard_cfg


@pytest.mark.asyncio
async def test_unified_ingress_once_discards_second_bot(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(shard_cfg, "is_sharding_active", lambda: False)
    monkeypatch.setattr("pallas.core.platform.ingress.gate.ingress_gate_active", lambda: True)
    monkeypatch.setattr("pallas.core.platform.ingress.gate.fleet_bot_ids_contains", lambda _uid: False)
    monkeypatch.setattr(
        "pallas.core.platform.ingress.gate.claim_federate_group_message_ingress",
        AsyncMock(return_value=True),
    )
    monkeypatch.setattr("pallas.core.platform.ingress.gate.ingress_fanout_bypasses_claim", lambda _plain: False)
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
        message=Message("测试 ingress"),
        raw_message="测试 ingress",
    )

    bot_a = FakeBot(111)
    bot_b = FakeBot(222)

    await ingress_group_message_gate(bot_a, event)
    with pytest.raises(IgnoredException):
        await ingress_group_message_gate(bot_b, event)


@pytest.mark.asyncio
async def test_unified_ingress_fanout_allows_all_bots(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(shard_cfg, "is_sharding_active", lambda: False)
    monkeypatch.setattr("pallas.core.platform.ingress.gate.ingress_gate_active", lambda: True)
    monkeypatch.setattr("pallas.core.platform.ingress.gate.fleet_bot_ids_contains", lambda _uid: False)
    monkeypatch.setattr(
        "pallas.core.platform.ingress.gate.claim_federate_group_message_ingress",
        AsyncMock(return_value=True),
    )
    monkeypatch.setattr("pallas.core.platform.ingress.gate.ingress_fanout_bypasses_claim", lambda _plain: True)
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
        message=Message("牛牛喝酒"),
        raw_message="牛牛喝酒",
    )

    await ingress_group_message_gate(FakeBot(111), event)
    await ingress_group_message_gate(FakeBot(222), event)


@pytest.mark.asyncio
async def test_unified_ingress_fanout_skips_federate_and_once_claim(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(shard_cfg, "is_sharding_active", lambda: False)
    monkeypatch.setattr("pallas.core.platform.ingress.gate.ingress_gate_active", lambda: True)
    monkeypatch.setattr("pallas.core.platform.ingress.gate.fleet_bot_ids_contains", lambda _uid: False)
    federate = AsyncMock(return_value=True)
    once = AsyncMock(return_value=True)
    monkeypatch.setattr("pallas.core.platform.ingress.gate.claim_federate_group_message_ingress", federate)
    monkeypatch.setattr("pallas.core.platform.ingress.claim_gate.try_claim_group_message_once", once)
    monkeypatch.setattr("pallas.core.platform.ingress.gate.ingress_fanout_bypasses_claim", lambda _plain: True)
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
        message=Message("牛牛"),
        raw_message="牛牛",
    )

    await ingress_group_message_gate(FakeBot(111), event)
    await ingress_group_message_gate(FakeBot(222), event)
    federate.assert_not_awaited()
    once.assert_not_awaited()


@pytest.mark.asyncio
async def test_unified_ingress_bypass_skips_federate_claim(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(shard_cfg, "is_sharding_active", lambda: False)
    monkeypatch.setattr("pallas.core.platform.ingress.gate.ingress_gate_active", lambda: True)
    monkeypatch.setattr("pallas.core.platform.ingress.gate.fleet_bot_ids_contains", lambda _uid: False)
    monkeypatch.setattr("pallas.core.platform.ingress.gate.ingress_fanout_bypasses_claim", lambda _plain: False)
    monkeypatch.setattr("pallas.core.platform.federate.ingress.federate_ingress_bypass_unified", lambda: True)
    federate = AsyncMock(return_value=True)
    monkeypatch.setattr("pallas.core.platform.federate.ingress.try_claim_cross_federate_message", federate)
    monkeypatch.setattr(
        "pallas.core.platform.ingress.claim_gate.try_claim_group_message_once", AsyncMock(return_value=True)
    )
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
        message=Message("测试 ingress"),
        raw_message="测试 ingress",
    )

    await ingress_group_message_gate(FakeBot(111), event)
    federate.assert_not_awaited()


def test_group_at_qq_ids_falls_back_to_raw_message_when_at_segment_missing() -> None:
    from pallas.core.platform.multi_bot.at_targets import group_at_qq_ids

    event = GroupMessageEvent.model_construct(
        time=100,
        self_id=2927116873,
        post_type="message",
        message_type="group",
        sub_type="normal",
        user_id=3023094357,
        group_id=733291779,
        message_id=1,
        message=Message("[reply:id=101092384] 不可以"),
        raw_message="[reply:id=101092384][at:qq=2927116873] 不可以",
    )

    assert group_at_qq_ids(event) == frozenset({2927116873})


@pytest.mark.asyncio
async def test_unified_ingress_discards_federate_peer_bot_before_claims(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(shard_cfg, "is_sharding_active", lambda: False)
    monkeypatch.setattr("pallas.core.platform.ingress.gate.ingress_gate_active", lambda: True)
    monkeypatch.setattr("pallas.core.platform.ingress.gate.fleet_bot_ids_contains", lambda _uid: False)
    monkeypatch.setattr("pallas.core.platform.ingress.gate.federate_peer_bot_ids_contains", lambda uid: int(uid) == 777)
    monkeypatch.setattr("pallas.core.platform.ingress.gate.ingress_fanout_bypasses_claim", lambda _plain: False)
    federate = AsyncMock(return_value=True)
    once = AsyncMock(return_value=True)
    monkeypatch.setattr("pallas.core.platform.ingress.gate.claim_federate_group_message_ingress", federate)
    monkeypatch.setattr("pallas.core.platform.ingress.claim_gate.try_claim_group_message_once", once)
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
        user_id=777,
        group_id=12345,
        message_id=1,
        message=Message("peer bot echo"),
        raw_message="peer bot echo",
    )

    with pytest.raises(IgnoredException):
        await ingress_group_message_gate(FakeBot(111), event)
    once.assert_not_awaited()
    federate.assert_not_awaited()


@pytest.mark.asyncio
async def test_unified_ingress_non_owner_deployment_skips_once_and_federate_claim(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(shard_cfg, "is_sharding_active", lambda: False)
    monkeypatch.setattr("pallas.core.platform.ingress.gate.ingress_gate_active", lambda: True)
    monkeypatch.setattr("pallas.core.platform.ingress.gate.fleet_bot_ids_contains", lambda _uid: False)
    monkeypatch.setattr("pallas.core.platform.ingress.gate.federate_peer_bot_ids_contains", lambda _uid: False)
    monkeypatch.setattr(
        "pallas.core.platform.ingress.gate.should_process_federate_group_on_current_deployment",
        lambda _group_id: False,
    )
    monkeypatch.setattr("pallas.core.platform.ingress.gate.ingress_fanout_bypasses_claim", lambda _plain: False)
    federate = AsyncMock(return_value=True)
    once = AsyncMock(return_value=True)
    monkeypatch.setattr("pallas.core.platform.ingress.gate.claim_federate_group_message_ingress", federate)
    monkeypatch.setattr("pallas.core.platform.ingress.claim_gate.try_claim_group_message_once", once)
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
        group_id=54321,
        message_id=1,
        message=Message("human message"),
        raw_message="human message",
    )

    with pytest.raises(IgnoredException):
        await ingress_group_message_gate(FakeBot(111), event)
    once.assert_not_awaited()
    federate.assert_not_awaited()


@pytest.mark.asyncio
async def test_unified_ingress_reuses_precomputed_plain_for_federate_claim(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(shard_cfg, "is_sharding_active", lambda: False)
    monkeypatch.setattr("pallas.core.platform.ingress.gate.ingress_gate_active", lambda: True)
    monkeypatch.setattr("pallas.core.platform.ingress.gate.fleet_bot_ids_contains", lambda _uid: False)
    monkeypatch.setattr("pallas.core.platform.ingress.gate.ingress_fanout_bypasses_claim", lambda _plain: False)
    monkeypatch.setattr(
        "pallas.core.platform.ingress.claim_gate.try_claim_group_message_once", AsyncMock(return_value=True)
    )

    async def fake_federate(event, **kwargs) -> bool:
        assert kwargs["plain"] == "测试 ingress"
        assert kwargs["body"] == "测试 ingress"
        return True

    monkeypatch.setattr("pallas.core.platform.ingress.gate.claim_federate_group_message_ingress", fake_federate)
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
        message=Message("测试 ingress"),
        raw_message="测试 ingress",
    )

    await ingress_group_message_gate(FakeBot(111), event)


@pytest.mark.asyncio
async def test_unified_ingress_only_allows_at_target_bot(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(shard_cfg, "is_sharding_active", lambda: False)
    monkeypatch.setattr("pallas.core.platform.ingress.gate.ingress_gate_active", lambda: True)
    monkeypatch.setattr("pallas.core.platform.ingress.gate.fleet_bot_ids_contains", lambda _uid: False)
    monkeypatch.setattr("pallas.core.platform.ingress.gate.get_fleet_bot_ids", lambda: frozenset({111, 222}))
    monkeypatch.setattr("pallas.core.platform.ingress.gate.ingress_fanout_bypasses_claim", lambda _plain: False)
    monkeypatch.setattr(
        "pallas.core.platform.ingress.claim_gate.try_claim_group_message_once", AsyncMock(return_value=True)
    )
    monkeypatch.setattr(
        "pallas.core.platform.ingress.gate.claim_federate_group_message_ingress",
        AsyncMock(return_value=True),
    )
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
        message=Message("[CQ:at,qq=111] 测试 ingress"),
        raw_message="[CQ:at,qq=111] 测试 ingress",
    )

    await ingress_group_message_gate(FakeBot(111), event)
    with pytest.raises(IgnoredException):
        await ingress_group_message_gate(FakeBot(222), event)


@pytest.mark.asyncio
async def test_unified_ingress_discards_self_sent_message_before_claims(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(shard_cfg, "is_sharding_active", lambda: False)
    monkeypatch.setattr("pallas.core.platform.ingress.gate.ingress_gate_active", lambda: True)
    once = AsyncMock(return_value=True)
    federate = AsyncMock(return_value=True)
    monkeypatch.setattr("pallas.core.platform.ingress.claim_gate.try_claim_group_message_once", once)
    monkeypatch.setattr("pallas.core.platform.ingress.gate.claim_federate_group_message_ingress", federate)
    from pallas.core.platform.ingress.gate import ingress_group_message_gate

    class FakeBot:
        self_id = "111"

    event = GroupMessageEvent.model_construct(
        time=100,
        self_id=111,
        post_type="message",
        message_type="group",
        sub_type="normal",
        user_id=111,
        group_id=12345,
        message_id=1,
        message=Message("插件回包"),
        raw_message="插件回包",
    )

    with pytest.raises(IgnoredException, match="self-sent"):
        await ingress_group_message_gate(FakeBot(), event)
    once.assert_not_awaited()
    federate.assert_not_awaited()
