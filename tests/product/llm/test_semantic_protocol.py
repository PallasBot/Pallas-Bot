import pytest

from pallas.product.llm import semantic_protocol as proto


@pytest.fixture(autouse=True)
def _clean_protocol_data(tmp_path, monkeypatch):
    monkeypatch.setenv("PALLAS_DATA_DIR", str(tmp_path))
    proto.clear_protocol_data_for_tests()
    yield
    proto.clear_protocol_data_for_tests()


def test_extract_protocol_commands_parses_explicit_candidates() -> None:
    assert proto.extract_protocol_commands(
        "请在 60 秒内发送「接受老婆赠送」，或发送「拒绝老婆赠送」，超时自动取消。"
    ) == ["接受老婆赠送", "拒绝老婆赠送"]
    assert proto.extract_protocol_commands("回复'签到'即可") == ["签到"]
    assert proto.extract_protocol_commands("没有命令") == []


def test_protocol_command_safe_rejects_risk_and_length() -> None:
    assert proto.protocol_command_safe("接受老婆赠送")
    assert proto.protocol_command_safe("签到")
    assert not proto.protocol_command_safe("转账100")
    assert not proto.protocol_command_safe("管理员踢人")
    assert not proto.protocol_command_safe("x")
    assert not proto.protocol_command_safe("命令" * 20)
    assert not proto.protocol_command_safe("[CQ:at,qq=1]")
    assert not proto.protocol_command_safe("接受 老婆")


def test_record_observation_requires_explicit_command_and_aggregates(tmp_path, monkeypatch) -> None:
    trigger = "请在 60 秒内发送「接受老婆赠送」，或发送「拒绝老婆赠送」"
    # 非显式候选：忽略
    assert not proto.record_protocol_observation(
        bot_id=100,
        group_id=42,
        trigger_text=trigger,
        reply_text="随便回一句",
        responder_id=11,
        source_message_id=1,
        created_at=100,
    )
    # 显式候选且安全：记录
    assert proto.record_protocol_observation(
        bot_id=100,
        group_id=42,
        trigger_text=trigger,
        reply_text="接受老婆赠送",
        responder_id=11,
        source_message_id=1,
        created_at=100,
    )
    assert proto.record_protocol_observation(
        bot_id=100,
        group_id=42,
        trigger_text=trigger,
        reply_text="接受老婆赠送",
        responder_id=12,
        source_message_id=2,
        created_at=200,
    )
    assert proto.record_protocol_observation(
        bot_id=100,
        group_id=42,
        trigger_text=trigger,
        reply_text="接受老婆赠送",
        responder_id=13,
        source_message_id=3,
        created_at=300,
    )
    # 幂等：同 observation_id 不重复计数
    assert not proto.record_protocol_observation(
        bot_id=100,
        group_id=42,
        trigger_text=trigger,
        reply_text="接受老婆赠送",
        responder_id=11,
        source_message_id=1,
        created_at=400,
    )

    status = proto.protocol_status()
    assert status["observation_count"] == 3
    assert status["pattern_count"] == 1
    assert status["eligible_pattern_count"] == 1


def test_resolve_protocol_candidate_gates_on_threshold_cooldown_and_recent_bot(tmp_path, monkeypatch) -> None:
    trigger = "请在 60 秒内发送「接受老婆赠送」，或发送「拒绝老婆赠送」"
    for mid, responder in ((1, 11), (2, 12), (3, 13)):
        proto.record_protocol_observation(
            bot_id=100,
            group_id=42,
            trigger_text=trigger,
            reply_text="接受老婆赠送",
            responder_id=responder,
            source_message_id=mid,
            created_at=mid * 100,
        )

    # 达到 3 次/2 人且当前 Bot 是最近发言者：可响应
    assert (
        proto.resolve_protocol_candidate(
            bot_id=100,
            group_id=42,
            trigger_text=trigger,
            recent_bot_id=100,
            nickname_targeted=True,
            now=1000,
        )
        == "接受老婆赠送"
    )
    # 最近发言者是其他 Bot：昵称定向不响应
    assert (
        proto.resolve_protocol_candidate(
            bot_id=100,
            group_id=42,
            trigger_text=trigger,
            recent_bot_id=200,
            nickname_targeted=True,
            now=1000,
        )
        == ""
    )
    # 冷却期内不响应
    proto.mark_protocol_sent(bot_id=100, group_id=42, now=1000)
    assert (
        proto.resolve_protocol_candidate(
            bot_id=100,
            group_id=42,
            trigger_text=trigger,
            recent_bot_id=100,
            nickname_targeted=True,
            now=1000 + 60,
        )
        == ""
    )
    # 冷却结束后恢复
    assert (
        proto.resolve_protocol_candidate(
            bot_id=100,
            group_id=42,
            trigger_text=trigger,
            recent_bot_id=100,
            nickname_targeted=True,
            now=1000 + proto._PROTOCOL_COOLDOWN_SEC + 1,
        )
        == "接受老婆赠送"
    )


def test_resolve_protocol_candidate_ignores_below_threshold(tmp_path, monkeypatch) -> None:
    trigger = "回复「签到」即可"
    proto.record_protocol_observation(
        bot_id=100,
        group_id=42,
        trigger_text=trigger,
        reply_text="签到",
        responder_id=11,
        source_message_id=1,
        created_at=100,
    )
    assert (
        proto.resolve_protocol_candidate(
            bot_id=100,
            group_id=42,
            trigger_text=trigger,
            recent_bot_id=100,
            nickname_targeted=True,
            now=200,
        )
        == ""
    )


def test_protocol_status_counts_eligible_patterns(tmp_path, monkeypatch) -> None:
    assert proto.protocol_status() == {
        "observation_count": 0,
        "pattern_count": 0,
        "eligible_pattern_count": 0,
    }


def test_protocol_patterns_are_scoped_per_group(tmp_path, monkeypatch) -> None:
    """群 A 积累的证据不得让群 B 相同模板直接响应。"""
    trigger = "请在 60 秒内发送「接受老婆赠送」"
    for mid, responder in ((1, 11), (2, 12), (3, 13)):
        proto.record_protocol_observation(
            bot_id=100,
            group_id=42,
            trigger_text=trigger,
            reply_text="接受老婆赠送",
            responder_id=responder,
            source_message_id=mid,
            created_at=mid * 100,
        )
    # 群 42 达到门槛：可响应
    assert (
        proto.resolve_protocol_candidate(
            bot_id=100,
            group_id=42,
            trigger_text=trigger,
            recent_bot_id=100,
            nickname_targeted=True,
            now=1000,
        )
        == "接受老婆赠送"
    )
    # 群 43 无任何观察：不得复用群 42 的证据
    assert (
        proto.resolve_protocol_candidate(
            bot_id=100,
            group_id=43,
            trigger_text=trigger,
            recent_bot_id=100,
            nickname_targeted=True,
            now=1000,
        )
        == ""
    )


def test_protocol_requires_explicit_or_recent_nickname_target() -> None:
    trigger = "回复「签到」即可"
    for mid, responder in ((1, 11), (2, 12), (3, 13)):
        proto.record_protocol_observation(
            bot_id=100,
            group_id=42,
            trigger_text=trigger,
            reply_text="签到",
            responder_id=responder,
            source_message_id=mid,
            created_at=mid,
        )

    assert not proto.resolve_protocol_candidate(
        bot_id=100,
        group_id=42,
        trigger_text=trigger,
        recent_bot_id=None,
    )
    assert not proto.resolve_protocol_candidate(
        bot_id=100,
        group_id=42,
        trigger_text=trigger,
        recent_bot_id=None,
        nickname_targeted=True,
    )
    assert (
        proto.resolve_protocol_candidate(
            bot_id=100,
            group_id=42,
            trigger_text=trigger,
            explicitly_targeted=True,
        )
        == "签到"
    )
