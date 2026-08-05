from __future__ import annotations

from pallas.core.platform.ingress.hosted_activity_gate import (
    HostedActivityIngressSpec,
    hosted_activity_claim_is_hosted,
    hosted_activity_ingress_passes,
    spec_host_gate_passes,
    spec_matches_in_room_command,
    spec_matches_speak_traffic,
)

SPY_SPEC = HostedActivityIngressSpec(
    plugin_key="who_is_spy",
    activity_namespace="spy_group",
    command_prefixes=(
        "牛牛卧底",
        "牛牛谁是卧底",
        "牛牛加入",
        "牛牛退出",
        "牛牛发身份",
        "牛牛开始",
        "牛牛投票",
        "牛牛局势",
        "牛牛结束",
    ),
    always_pass_prefixes=("牛牛卧底", "牛牛谁是卧底", "牛牛结束"),
    session_flag="session_active",
    speak_at_fleet_bot_only=True,
)


def test_spec_command_prefixes() -> None:
    assert spec_matches_in_room_command(SPY_SPEC, "牛牛加入")
    assert not spec_matches_in_room_command(SPY_SPEC, "牛牛卧底")
    assert not spec_matches_in_room_command(SPY_SPEC, "牛牛")


def test_hosted_ingress_passes_when_no_host_gate(monkeypatch) -> None:
    monkeypatch.setattr(
        "pallas.core.platform.ingress.hosted_activity_gate.loaded_hosted_activity_specs",
        lambda: (SPY_SPEC,),
    )
    monkeypatch.setattr(
        "pallas.core.platform.ingress.hosted_activity_gate.needs_group_host_bot_gate",
        lambda: False,
    )
    assert hosted_activity_ingress_passes(1, 100, "牛牛加入") is True


def test_hosted_activity_claim_detects_live_plaintext_traffic(monkeypatch) -> None:
    monkeypatch.setattr(
        "pallas.core.platform.ingress.hosted_activity_gate.loaded_hosted_activity_specs",
        lambda: (SPY_SPEC,),
    )
    monkeypatch.setattr(
        "pallas.core.platform.ingress.hosted_activity_gate.hosted_activity_live",
        lambda **_k: True,
    )
    monkeypatch.setattr(
        "pallas.core.platform.ingress.hosted_activity_gate.coord_session_active",
        lambda _ns, _gid, **_kwargs: True,
    )
    assert hosted_activity_claim_is_hosted(100, "帕拉斯", at_fleet_bot=True) is True
    assert hosted_activity_claim_is_hosted(100, "帕拉斯", at_fleet_bot=False) is False


def test_hosted_ingress_open_end_pass_without_room(monkeypatch) -> None:
    monkeypatch.setattr(
        "pallas.core.platform.ingress.hosted_activity_gate.loaded_hosted_activity_specs",
        lambda: (SPY_SPEC,),
    )
    monkeypatch.setattr(
        "pallas.core.platform.ingress.hosted_activity_gate.needs_group_host_bot_gate",
        lambda: True,
    )
    monkeypatch.setattr(
        "pallas.core.platform.ingress.hosted_activity_gate.hosted_activity_live",
        lambda **_k: False,
    )
    assert hosted_activity_ingress_passes(999, 100, "牛牛卧底") is True
    assert hosted_activity_ingress_passes(999, 100, "牛牛结束") is True


def test_hosted_ingress_open_end_require_host_when_room_live(monkeypatch) -> None:
    monkeypatch.setattr(
        "pallas.core.platform.ingress.hosted_activity_gate.loaded_hosted_activity_specs",
        lambda: (SPY_SPEC,),
    )
    monkeypatch.setattr(
        "pallas.core.platform.ingress.hosted_activity_gate.needs_group_host_bot_gate",
        lambda: True,
    )
    monkeypatch.setattr(
        "pallas.core.platform.ingress.hosted_activity_gate.hosted_activity_live",
        lambda **_k: True,
    )

    def holder(plugin: str, group_id: int, bot_id: int) -> bool:
        assert plugin == "who_is_spy"
        return bot_id == 42

    monkeypatch.setattr(
        "pallas.core.platform.ingress.hosted_activity_gate.is_group_owned_gate_holder_sync",
        holder,
    )
    assert hosted_activity_ingress_passes(42, 100, "牛牛卧底") is True
    assert hosted_activity_ingress_passes(42, 100, "牛牛结束") is True
    assert hosted_activity_ingress_passes(99, 100, "牛牛卧底") is False
    assert hosted_activity_ingress_passes(99, 100, "牛牛结束") is False


def test_hosted_ingress_in_room_requires_host(monkeypatch) -> None:
    monkeypatch.setattr(
        "pallas.core.platform.ingress.hosted_activity_gate.needs_group_host_bot_gate",
        lambda: True,
    )
    monkeypatch.setattr(
        "pallas.core.platform.ingress.hosted_activity_gate.hosted_activity_live",
        lambda **_k: True,
    )

    def holder(plugin: str, group_id: int, bot_id: int) -> bool:
        assert plugin == "who_is_spy"
        return bot_id == 42

    monkeypatch.setattr(
        "pallas.core.platform.ingress.hosted_activity_gate.is_group_owned_gate_holder_sync",
        holder,
    )
    assert spec_host_gate_passes(SPY_SPEC, 42, 100, "牛牛加入", at_fleet_bot=False) is True
    assert spec_host_gate_passes(SPY_SPEC, 99, 100, "牛牛加入", at_fleet_bot=False) is False


def test_hosted_ingress_speak_traffic_uses_unified_owned_gate(monkeypatch) -> None:
    from pallas.core.platform.multi_bot.dedup import bind_group_owned_gate_sync, release_group_owned_gate_sync

    monkeypatch.setattr("pallas.core.platform.multi_bot.dedup.sharding_active", lambda: False)
    monkeypatch.setattr(
        "pallas.core.platform.ingress.hosted_activity_gate.needs_group_host_bot_gate",
        lambda: True,
    )
    monkeypatch.setattr(
        "pallas.core.platform.ingress.hosted_activity_gate.hosted_activity_live",
        lambda **_k: True,
    )
    bind_group_owned_gate_sync("who_is_spy", 100, 42, gate_sec=60)
    try:
        assert spec_host_gate_passes(SPY_SPEC, 42, 100, "回答", at_fleet_bot=True) is True
        assert spec_host_gate_passes(SPY_SPEC, 99, 100, "回答", at_fleet_bot=True) is False
    finally:
        release_group_owned_gate_sync("who_is_spy", 100)


def test_hosted_ingress_no_room_passes_join(monkeypatch) -> None:
    monkeypatch.setattr(
        "pallas.core.platform.ingress.hosted_activity_gate.needs_group_host_bot_gate",
        lambda: True,
    )
    monkeypatch.setattr(
        "pallas.core.platform.ingress.hosted_activity_gate.hosted_activity_live",
        lambda **_k: False,
    )
    assert spec_host_gate_passes(SPY_SPEC, 99, 100, "牛牛加入", at_fleet_bot=False) is True


def test_spec_speak_traffic_accepts_owned_gate_without_session_flag(monkeypatch) -> None:
    monkeypatch.setattr(
        "pallas.core.platform.ingress.hosted_activity_gate.coord_session_active",
        lambda _ns, _gid, **_: False,
    )
    monkeypatch.setattr(
        "pallas.core.platform.ingress.hosted_activity_gate.read_group_owned_gate_bot_id_sync",
        lambda _plugin, _gid: 42,
    )
    assert spec_matches_speak_traffic(SPY_SPEC, 7, "帕拉斯", at_fleet_bot=True) is True


def test_spec_speak_traffic_at_bot_only(monkeypatch) -> None:
    monkeypatch.setattr(
        "pallas.core.platform.ingress.hosted_activity_gate.coord_session_active",
        lambda ns, gid, **_: gid == 7,
    )
    monkeypatch.setattr(
        "pallas.core.platform.ingress.hosted_activity_gate.read_group_owned_gate_bot_id_sync",
        lambda _plugin, _gid: None,
    )
    assert spec_matches_speak_traffic(SPY_SPEC, 7, "随便说说", at_fleet_bot=True) is True
    assert spec_matches_speak_traffic(SPY_SPEC, 7, "随便说说", at_fleet_bot=False) is False
    assert spec_matches_speak_traffic(SPY_SPEC, 7, "牛牛加入", at_fleet_bot=True) is False
