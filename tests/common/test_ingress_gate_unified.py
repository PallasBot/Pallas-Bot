from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from nonebot.adapters.onebot.v11 import GroupMessageEvent, Message, NoticeEvent
from nonebot.exception import IgnoredException

from pallas.core.platform.ingress.group_admin_owner import GroupAdminOwnerIngressDecision
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
async def test_group_admin_owner_blocks_before_fanout_bypass(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(shard_cfg, "is_sharding_active", lambda: False)
    monkeypatch.setattr("pallas.core.platform.ingress.gate.ingress_gate_active", lambda: True)
    monkeypatch.setattr("pallas.core.platform.ingress.gate.fleet_bot_ids_contains", lambda _uid: False)
    monkeypatch.setattr(
        "pallas.core.platform.ingress.gate.group_admin_owner_ingress_decision",
        AsyncMock(return_value=GroupAdminOwnerIngressDecision(passes=False)),
    )
    fanout = MagicMock(return_value=True)
    monkeypatch.setattr("pallas.core.platform.ingress.gate.ingress_fanout_bypasses_claim", fanout)
    from pallas.core.platform.ingress.gate import ingress_group_message_gate

    event = GroupMessageEvent.model_construct(
        time=100,
        self_id=111,
        post_type="message",
        message_type="group",
        sub_type="normal",
        user_id=999,
        group_id=12345,
        message_id=1,
        message=Message("牛牛轮盘"),
        raw_message="牛牛轮盘",
    )

    with pytest.raises(IgnoredException, match="group admin owner mismatch"):
        await ingress_group_message_gate(type("Bot", (), {"self_id": "111"})(), event)
    fanout.assert_not_called()


@pytest.mark.asyncio
async def test_group_admin_owner_falls_back_to_fanout_when_observation_is_unknown(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(shard_cfg, "is_sharding_active", lambda: False)
    monkeypatch.setattr("pallas.core.platform.ingress.gate.ingress_gate_active", lambda: True)
    monkeypatch.setattr("pallas.core.platform.ingress.gate.fleet_bot_ids_contains", lambda _uid: False)
    monkeypatch.setattr(
        "pallas.core.platform.ingress.gate.group_admin_owner_ingress_decision",
        AsyncMock(return_value=GroupAdminOwnerIngressDecision(passes=True, fallback_to_fanout=True)),
    )
    fanout = MagicMock(return_value=False)
    monkeypatch.setattr("pallas.core.platform.ingress.gate.ingress_fanout_bypasses_claim", fanout)
    from pallas.core.platform.ingress.gate import ingress_group_message_gate

    event = GroupMessageEvent.model_construct(
        time=100,
        self_id=111,
        post_type="message",
        message_type="group",
        sub_type="normal",
        user_id=999,
        group_id=12345,
        message_id=1,
        message=Message("牛牛轮盘"),
        raw_message="牛牛轮盘",
    )

    await ingress_group_message_gate(type("Bot", (), {"self_id": "111"})(), event)
    fanout.assert_not_called()


@pytest.mark.asyncio
async def test_group_admin_notice_ignores_non_local_bot(monkeypatch: pytest.MonkeyPatch) -> None:
    from pallas.core.platform.ingress import gate

    record_notice = MagicMock()
    monkeypatch.setattr(gate, "get_bots", lambda: {"111": object()})
    monkeypatch.setattr(
        "pallas.core.platform.multi_bot.group_admin_capability.record_group_admin_notice",
        record_notice,
    )
    monkeypatch.setattr(gate, "ingress_notice_gate", AsyncMock())
    event = NoticeEvent.model_construct(
        time=100,
        self_id=111,
        post_type="notice",
        notice_type="group_admin",
        sub_type="set",
        group_id=12345,
        user_id=999,
    )

    await gate.ingress_notice_preprocess(type("Bot", (), {"self_id": "111"})(), event)

    record_notice.assert_not_called()


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
async def test_unified_ingress_pallas_status_uses_local_claim_without_federate(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(shard_cfg, "is_sharding_active", lambda: False)
    monkeypatch.setattr("pallas.core.platform.ingress.gate.ingress_gate_active", lambda: True)
    monkeypatch.setattr("pallas.core.platform.ingress.gate.fleet_bot_ids_contains", lambda _uid: False)
    monkeypatch.setattr("pallas.core.platform.ingress.gate.federate_peer_bot_ids_contains", lambda _uid: False)
    monkeypatch.setattr("pallas.core.platform.ingress.gate.ingress_fanout_bypasses_claim", lambda _plain: False)
    monkeypatch.setattr(
        "pallas.core.platform.ingress.gate.ingress_once_claim_safe_before_host_gates",
        lambda *_args, **_kwargs: True,
    )
    owner = MagicMock(return_value=True)
    federate = AsyncMock(return_value=True)
    local_claim = AsyncMock(return_value=[])
    monkeypatch.setattr("pallas.core.platform.ingress.gate.should_process_federate_group_on_current_deployment", owner)
    monkeypatch.setattr("pallas.core.platform.ingress.gate.claim_federate_group_message_ingress", federate)
    monkeypatch.setattr("pallas.core.platform.ingress.gate.run_ingress_message_claim", local_claim)
    monkeypatch.setattr(
        "pallas.core.platform.ingress.gate.hosted_activity_ingress_passes", lambda *_args, **_kwargs: True
    )
    monkeypatch.setattr("pallas.core.platform.ingress.gate.dream_session_ingress_passes", AsyncMock(return_value=True))
    from pallas.core.platform.ingress.gate import ingress_group_message_gate

    class FakeBot:
        self_id = "111"

    event = GroupMessageEvent.model_construct(
        time=100,
        self_id=111,
        post_type="message",
        message_type="group",
        sub_type="normal",
        user_id=999,
        group_id=12345,
        message_id=1,
        message=Message("#pallas"),
        raw_message="#pallas",
    )

    await ingress_group_message_gate(FakeBot(), event)

    local_claim.assert_awaited_once()
    owner.assert_not_called()
    federate.assert_not_awaited()


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
async def test_unified_ingress_non_owner_deployment_skips_command_once_and_federate_claim(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(shard_cfg, "is_sharding_active", lambda: False)
    monkeypatch.setattr("pallas.core.platform.ingress.gate.ingress_gate_active", lambda: True)
    monkeypatch.setattr("pallas.core.platform.ingress.gate.fleet_bot_ids_contains", lambda _uid: False)
    monkeypatch.setattr("pallas.core.platform.ingress.gate.federate_peer_bot_ids_contains", lambda _uid: False)
    monkeypatch.setattr(
        "pallas.core.platform.ingress.gate.should_process_federate_group_on_current_deployment",
        lambda _group_id, **_kw: False,
    )
    monkeypatch.setattr("pallas.core.platform.ingress.gate.ingress_fanout_bypasses_claim", lambda _plain: False)
    monkeypatch.setattr("pallas.core.platform.ingress.gate.legacy_command_traffic", lambda _plain, **_kw: True)
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
        message=Message("牛牛帮助"),
        raw_message="牛牛帮助",
    )

    with pytest.raises(IgnoredException):
        await ingress_group_message_gate(FakeBot(111), event)
    once.assert_not_awaited()
    federate.assert_not_awaited()


@pytest.mark.asyncio
async def test_unified_ingress_yields_peer_covered_command_even_if_not_local_command_traffic(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """本机未装决斗插件时不认「牛牛决斗」为本地命令，但仍须让给有能力的对端，不得抢 federate claim。"""
    monkeypatch.setattr(shard_cfg, "is_sharding_active", lambda: False)
    monkeypatch.setattr("pallas.core.platform.ingress.gate.ingress_gate_active", lambda: True)
    monkeypatch.setattr("pallas.core.platform.ingress.gate.fleet_bot_ids_contains", lambda _uid: False)
    monkeypatch.setattr("pallas.core.platform.ingress.gate.federate_peer_bot_ids_contains", lambda _uid: False)
    monkeypatch.setattr(
        "pallas.core.platform.ingress.gate.should_yield_federate_ingress_for_peer_command",
        lambda _group_id, **_kw: True,
    )
    monkeypatch.setattr("pallas.core.platform.ingress.gate.ingress_fanout_bypasses_claim", lambda _plain: False)
    monkeypatch.setattr("pallas.core.platform.ingress.gate.legacy_command_traffic", lambda _plain, **_kw: False)
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
        group_id=1076683542,
        message_id=1,
        message=Message("牛牛决斗"),
        raw_message="牛牛决斗",
    )

    with pytest.raises(IgnoredException):
        await ingress_group_message_gate(FakeBot(111), event)
    once.assert_not_awaited()
    federate.assert_not_awaited()


@pytest.mark.asyncio
async def test_unified_ingress_peer_declared_command_skips_owner_mismatch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """本机未装画画、但对端显式宣告了牛牛画画时，本机识别为命令流量并让出，不得抢 federate claim。"""
    monkeypatch.setattr(shard_cfg, "is_sharding_active", lambda: False)
    monkeypatch.setattr("pallas.core.platform.ingress.gate.ingress_gate_active", lambda: True)
    monkeypatch.setattr("pallas.core.platform.ingress.gate.fleet_bot_ids_contains", lambda _uid: False)
    monkeypatch.setattr("pallas.core.platform.ingress.gate.federate_peer_bot_ids_contains", lambda _uid: False)
    monkeypatch.setattr(
        "pallas.core.platform.ingress.gate.should_process_federate_group_on_current_deployment",
        lambda _group_id, **_kw: False,
    )
    monkeypatch.setattr("pallas.core.platform.ingress.gate.ingress_fanout_bypasses_claim", lambda _plain: False)
    monkeypatch.setattr("pallas.core.platform.ingress.gate.legacy_command_traffic", lambda _plain, **_kw: False)
    monkeypatch.setattr(
        "pallas.core.platform.ingress.gate.federate_peer_declared_command_plaintext",
        lambda _plain: True,
    )
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
        group_id=1076683542,
        message_id=1,
        message=Message("牛牛画画 猫娘"),
        raw_message="牛牛画画 猫娘",
    )

    with pytest.raises(IgnoredException):
        await ingress_group_message_gate(FakeBot(111), event)
    once.assert_not_awaited()
    federate.assert_not_awaited()


def test_command_lane_traffic_combines_local_and_peer_declared(monkeypatch: pytest.MonkeyPatch) -> None:
    from pallas.core.platform.ingress import gate

    monkeypatch.setattr(gate, "legacy_command_traffic", lambda _plain, **_kw: False)
    monkeypatch.setattr(gate, "federate_peer_declared_command_plaintext", lambda _plain: True)
    assert gate.command_lane_traffic("牛牛画画") is True

    monkeypatch.setattr(gate, "federate_peer_declared_command_plaintext", lambda _plain: False)
    assert gate.command_lane_traffic("牛牛画画") is False

    monkeypatch.setattr(gate, "legacy_command_traffic", lambda _plain, **_kw: True)
    assert gate.command_lane_traffic("牛牛画画") is True


@pytest.mark.asyncio
async def test_unified_ingress_non_owner_still_claims_chat_traffic(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(shard_cfg, "is_sharding_active", lambda: False)
    monkeypatch.setattr("pallas.core.platform.ingress.gate.ingress_gate_active", lambda: True)
    monkeypatch.setattr("pallas.core.platform.ingress.gate.fleet_bot_ids_contains", lambda _uid: False)
    monkeypatch.setattr("pallas.core.platform.ingress.gate.federate_peer_bot_ids_contains", lambda _uid: False)
    monkeypatch.setattr(
        "pallas.core.platform.ingress.gate.should_process_federate_group_on_current_deployment",
        lambda _group_id, **_kw: False,
    )
    monkeypatch.setattr("pallas.core.platform.ingress.gate.ingress_fanout_bypasses_claim", lambda _plain: False)
    monkeypatch.setattr("pallas.core.platform.ingress.gate.legacy_command_traffic", lambda _plain, **_kw: False)
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
        message=Message("今天天气怎么样"),
        raw_message="今天天气怎么样",
    )

    await ingress_group_message_gate(FakeBot(111), event)
    once.assert_awaited()
    federate.assert_awaited()


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
async def test_unified_ingress_at_target_skips_federate_claim(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(shard_cfg, "is_sharding_active", lambda: False)
    monkeypatch.setattr("pallas.core.platform.ingress.gate.ingress_gate_active", lambda: True)
    monkeypatch.setattr("pallas.core.platform.ingress.gate.fleet_bot_ids_contains", lambda _uid: False)
    monkeypatch.setattr("pallas.core.platform.ingress.gate.get_fleet_bot_ids", lambda: frozenset({111}))
    monkeypatch.setattr("pallas.core.platform.ingress.gate.ingress_fanout_bypasses_claim", lambda _plain: False)
    monkeypatch.setattr(
        "pallas.core.platform.ingress.claim_gate.try_claim_group_message_once", AsyncMock(return_value=True)
    )
    federate = AsyncMock(return_value=False)
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
        user_id=999,
        group_id=733291779,
        message_id=1,
        message=Message("[CQ:at,qq=111]"),
        raw_message="[CQ:at,qq=111]",
    )

    await ingress_group_message_gate(FakeBot(), event)

    federate.assert_not_awaited()


@pytest.mark.asyncio
async def test_unified_ingress_at_target_command_skips_federate_ownership(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(shard_cfg, "is_sharding_active", lambda: False)
    monkeypatch.setattr("pallas.core.platform.ingress.gate.ingress_gate_active", lambda: True)
    monkeypatch.setattr("pallas.core.platform.ingress.gate.fleet_bot_ids_contains", lambda _uid: False)
    monkeypatch.setattr("pallas.core.platform.ingress.gate.get_fleet_bot_ids", lambda: frozenset({111}))
    monkeypatch.setattr("pallas.core.platform.ingress.gate.ingress_fanout_bypasses_claim", lambda _plain: False)
    monkeypatch.setattr(
        "pallas.core.platform.ingress.claim_gate.try_claim_group_message_once", AsyncMock(return_value=True)
    )
    peer_command = MagicMock(return_value=True)
    owner = MagicMock(return_value=False)
    monkeypatch.setattr(
        "pallas.core.platform.ingress.gate.should_yield_federate_ingress_for_peer_command",
        peer_command,
    )
    monkeypatch.setattr(
        "pallas.core.platform.ingress.gate.should_process_federate_group_on_current_deployment",
        owner,
    )
    from pallas.core.platform.ingress.gate import ingress_group_message_gate

    class FakeBot:
        self_id = "111"

    event = GroupMessageEvent.model_construct(
        time=100,
        self_id=111,
        post_type="message",
        message_type="group",
        sub_type="normal",
        user_id=999,
        group_id=733291779,
        message_id=1,
        message=Message("[CQ:at,qq=111] 牛牛点歌 测试"),
        raw_message="[CQ:at,qq=111] 牛牛点歌 测试",
    )

    await ingress_group_message_gate(FakeBot(), event)

    peer_command.assert_not_called()
    owner.assert_not_called()


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


@pytest.mark.asyncio
async def test_unified_ingress_marks_winning_alias_for_llm_chat(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(shard_cfg, "is_sharding_active", lambda: False)
    monkeypatch.setattr("pallas.core.platform.ingress.gate.ingress_gate_active", lambda: True)
    monkeypatch.setattr("pallas.core.platform.ingress.gate.fleet_bot_ids_contains", lambda _uid: False)
    monkeypatch.setattr(
        "pallas.core.platform.ingress.alias_route.fleet_bots_matching_plain",
        lambda _plain, **_kwargs: frozenset({111}),
    )
    monkeypatch.setattr(
        "pallas.core.platform.ingress.gate.claim_federate_group_message_ingress",
        AsyncMock(return_value=True),
    )
    from pallas.core.platform.ingress.gate import ingress_group_message_gate

    event = GroupMessageEvent.model_construct(
        time=100,
        self_id=111,
        post_type="message",
        message_type="group",
        sub_type="normal",
        user_id=999,
        group_id=12345,
        message_id=1,
        message=Message("泰坦牛牛吃饭了没"),
        raw_message="泰坦牛牛吃饭了没",
    )

    await ingress_group_message_gate(type("Bot", (), {"self_id": "111"})(), event)

    assert getattr(event, "_pallas_llm_alias_hard_trigger", False) is True
