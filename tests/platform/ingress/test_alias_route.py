"""入站别名路由：点名同伴时让出 claim。"""

from __future__ import annotations

from pallas.core.platform.ingress.alias_route import (
    clear_alias_route_state,
    fleet_bots_matching_plain,
    remember_learned_self_aliases,
    should_yield_ingress_for_peer_alias,
    speak_aliases_for_bot_sync,
)


def test_should_yield_when_peer_display_name_mentioned(monkeypatch) -> None:
    clear_alias_route_state()
    monkeypatch.setattr(
        "pallas.core.platform.multi_bot.fleet.get_fleet_bot_ids",
        lambda: frozenset({2357682124, 3129723001, 3879348674}),
    )
    monkeypatch.setattr(
        "pallas.product.persona.self_identity.resolve_cached_login_nickname",
        lambda bot_id: {
            2357682124: "漂亮牛",
            3129723001: "芝士牛牛",
            3879348674: "牛牛测试机",
        }.get(int(bot_id), ""),
    )
    plain = "漂亮牛听到了说一声收到"
    assert fleet_bots_matching_plain(plain) == frozenset({2357682124})
    assert should_yield_ingress_for_peer_alias(self_id=3879348674, plain_text=plain)
    assert should_yield_ingress_for_peer_alias(self_id=3129723001, plain_text=plain)
    assert not should_yield_ingress_for_peer_alias(self_id=2357682124, plain_text=plain)


def test_shared_generic_niu_niu_does_not_exclusive_match(monkeypatch) -> None:
    clear_alias_route_state()
    monkeypatch.setattr(
        "pallas.core.platform.multi_bot.fleet.get_fleet_bot_ids",
        lambda: frozenset({11, 22}),
    )
    monkeypatch.setattr(
        "pallas.product.persona.self_identity.resolve_cached_login_nickname",
        lambda _bot_id: "",
    )
    plain = "牛牛出来一下"
    assert fleet_bots_matching_plain(plain) == frozenset()
    assert not should_yield_ingress_for_peer_alias(self_id=11, plain_text=plain)


def test_pallas_exclusive_yield(monkeypatch) -> None:
    clear_alias_route_state()
    monkeypatch.setattr(
        "pallas.core.platform.multi_bot.fleet.get_fleet_bot_ids",
        lambda: frozenset({11, 22, 33}),
    )
    monkeypatch.setattr(
        "pallas.product.persona.self_identity.resolve_cached_login_nickname",
        lambda bot_id: {11: "帕拉斯", 22: "豆包牛牛", 33: "牛牛测试机"}.get(int(bot_id), ""),
    )
    plain = "帕拉斯出"
    assert fleet_bots_matching_plain(plain) == frozenset({11})
    assert should_yield_ingress_for_peer_alias(self_id=22, plain_text=plain)
    assert not should_yield_ingress_for_peer_alias(self_id=11, plain_text=plain)


def test_doubao_short_alias_exclusive(monkeypatch) -> None:
    clear_alias_route_state()
    monkeypatch.setattr(
        "pallas.core.platform.multi_bot.fleet.get_fleet_bot_ids",
        lambda: frozenset({11, 22}),
    )
    monkeypatch.setattr(
        "pallas.product.persona.self_identity.resolve_cached_login_nickname",
        lambda bot_id: {11: "帕拉斯", 22: "豆包牛牛"}.get(int(bot_id), ""),
    )
    plain = "豆包来一下"
    assert fleet_bots_matching_plain(plain) == frozenset({22})
    assert should_yield_ingress_for_peer_alias(self_id=11, plain_text=plain)


def test_no_yield_without_alias_hit(monkeypatch) -> None:
    clear_alias_route_state()
    monkeypatch.setattr(
        "pallas.core.platform.multi_bot.fleet.get_fleet_bot_ids",
        lambda: frozenset({11, 22}),
    )
    monkeypatch.setattr(
        "pallas.product.persona.self_identity.resolve_cached_login_nickname",
        lambda _bot_id: "甲牛",
    )
    assert not should_yield_ingress_for_peer_alias(self_id=11, plain_text="今天吃面")


def test_learned_alias_feeds_route_cache(monkeypatch) -> None:
    clear_alias_route_state()
    monkeypatch.setattr(
        "pallas.core.platform.multi_bot.fleet.get_fleet_bot_ids",
        lambda: frozenset({11, 22}),
    )
    monkeypatch.setattr(
        "pallas.product.persona.self_identity.resolve_cached_login_nickname",
        lambda _bot_id: "",
    )
    remember_learned_self_aliases(11, ["暗号甲"])
    plain = "暗号甲在吗"
    assert 11 in fleet_bots_matching_plain(plain)
    assert should_yield_ingress_for_peer_alias(self_id=22, plain_text=plain)
    assert not should_yield_ingress_for_peer_alias(self_id=11, plain_text=plain)
    assert "暗号甲" in speak_aliases_for_bot_sync(11)
