from __future__ import annotations

import re
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from src.platform.ingress import matcher_activation as activation
from src.platform.ingress import route_index


class _CommandMatcher:
    plugin_name = "src.plugins.help"
    block = False
    rule = MagicMock()


class _PassiveMatcher:
    plugin_name = "src.plugins.repeater"
    block = False
    rule = MagicMock()


class _BlockMatcher:
    plugin_name = "src.plugins.duel"
    block = True
    rule = MagicMock()


class _HelpMatcher:
    plugin_name = "src.plugins.help"
    block = False
    rule = MagicMock()


class _DuelMatcher:
    plugin_name = "src.plugins.duel"
    block = False
    rule = MagicMock()


def _fake_plugin(
    *,
    module_name: str,
    menu_data: list | None = None,
    ingress_fanout: dict | None = None,
    ingress_route: dict | None = None,
) -> SimpleNamespace:
    extra: dict = {}
    if menu_data is not None:
        extra["menu_data"] = menu_data
    if ingress_fanout is not None:
        extra["ingress_fanout"] = ingress_fanout
    if ingress_route is not None:
        extra["ingress_route"] = ingress_route
    return SimpleNamespace(
        module=SimpleNamespace(__name__=module_name),
        metadata=SimpleNamespace(extra=extra),
    )


@pytest.fixture(autouse=True)
def reset_route_index() -> None:
    route_index.clear_route_index_cache()
    activation.matcher_is_command_only.cache_clear()
    activation.matcher_module_key.cache_clear()
    yield
    route_index.clear_route_index_cache()
    activation.matcher_is_command_only.cache_clear()
    activation.matcher_module_key.cache_clear()


def test_build_route_index_from_menu_and_fanout(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        route_index,
        "get_loaded_plugins",
        lambda: [
            _fake_plugin(
                module_name="src.plugins.help",
                menu_data=[{"trigger_condition": "牛牛帮助 〈插件名〉"}],
            ),
            _fake_plugin(
                module_name="src.plugins.roulette",
                ingress_fanout={
                    "plaintexts": ["牛牛轮盘"],
                    "prefixes": ["牛牛救一下"],
                },
            ),
            _fake_plugin(
                module_name="src.plugins.duel",
                ingress_fanout={
                    "regexes": [r"^八角笼牛\s*$"],
                },
            ),
        ],
    )

    index = route_index.build_route_index()

    assert "help" in index.indexed_modules
    assert index.prefix_to_modules["牛牛帮助"] == frozenset({"help"})
    assert index.exact_to_modules["牛牛轮盘"] == frozenset({"roulette"})
    assert index.prefix_to_modules["牛牛救一下"] == frozenset({"roulette"})
    assert any(module == "duel" for module, _ in index.regex_entries)


def test_build_route_index_prefers_explicit_command_prefixes_and_exacts(monkeypatch: pytest.MonkeyPatch) -> None:
    plugins = [
        _fake_plugin(
            module_name="src.plugins.chat",
            menu_data=[{"trigger_condition": "@牛牛 / 牛牛 + 文本"}],
        ),
        _fake_plugin(
            module_name="src.plugins.sing",
            menu_data=[{"trigger_condition": "牛牛唱歌 歌曲名 [key=±N]"}],
        ),
        _fake_plugin(
            module_name="src.plugins.connectivity",
            menu_data=[{"trigger_condition": "牛牛连通 / 牛牛网关"}],
        ),
    ]
    plugins[0].metadata.extra["command_prefixes"] = ["牛牛"]
    plugins[1].metadata.extra["command_prefixes"] = ["牛牛唱歌", "牛牛继续唱", "牛牛接着唱", "牛牛点歌"]
    plugins[2].metadata.extra["exact_plaintexts"] = ["牛牛连通", "牛牛网关"]

    monkeypatch.setattr(
        route_index,
        "get_loaded_plugins",
        lambda: plugins,
    )

    index = route_index.build_route_index()

    assert index.prefix_to_modules["牛牛"] == frozenset({"chat"})
    assert index.prefix_to_modules["牛牛唱歌"] == frozenset({"sing"})
    assert index.prefix_to_modules["牛牛点歌"] == frozenset({"sing"})
    assert index.exact_to_modules["牛牛连通"] == frozenset({"connectivity"})
    assert index.exact_to_modules["牛牛网关"] == frozenset({"connectivity"})


def test_build_route_index_supports_multiple_explicit_plugin_routes(monkeypatch: pytest.MonkeyPatch) -> None:
    plugins = [
        _fake_plugin(module_name="src.plugins.draw", menu_data=[{"trigger_condition": "牛牛画画 …"}]),
        _fake_plugin(module_name="src.plugins.help", menu_data=[{"trigger_condition": "牛牛帮助 〈插件名〉"}]),
        _fake_plugin(module_name="src.plugins.bot_status", menu_data=[{"trigger_condition": "牛牛报数 / 牛牛出列"}]),
        _fake_plugin(module_name="src.plugins.roulette", menu_data=[{"trigger_condition": "牛牛轮盘"}]),
    ]
    plugins[0].metadata.extra["command_prefixes"] = ["牛牛画画"]
    plugins[1].metadata.extra["command_prefixes"] = ["牛牛帮助", "牛牛开启", "牛牛关闭"]
    plugins[2].metadata.extra["exact_plaintexts"] = ["牛牛在吗", "测试邮件", "牛牛报数", "牛牛出列"]
    plugins[3].metadata.extra["exact_plaintexts"] = ["牛牛轮盘", "牛牛开枪"]
    plugins[3].metadata.extra["command_prefixes"] = ["牛牛救一下", "牛牛补一枪"]

    monkeypatch.setattr(route_index, "get_loaded_plugins", lambda: plugins)

    index = route_index.build_route_index()

    assert index.prefix_to_modules["牛牛画画"] == frozenset({"draw"})
    assert index.prefix_to_modules["牛牛帮助"] == frozenset({"help"})
    assert index.prefix_to_modules["牛牛救一下"] == frozenset({"roulette"})
    assert index.exact_to_modules["牛牛报数"] == frozenset({"bot_status"})
    assert index.exact_to_modules["牛牛轮盘"] == frozenset({"roulette"})


def test_resolve_message_route_prefix_and_exact(monkeypatch: pytest.MonkeyPatch) -> None:
    snapshot = route_index.RouteIndexSnapshot(
        prefix_to_modules={"牛牛帮助": frozenset({"help"})},
        exact_to_modules={"牛牛轮盘": frozenset({"roulette"})},
        regex_entries=(("duel", re.compile(r"^八角笼牛$")),),
        always_run_modules=frozenset(),
        passive_modules=frozenset({"repeater"}),
        indexed_modules=frozenset({"help", "roulette", "duel"}),
    )
    monkeypatch.setattr(route_index, "get_route_index", lambda: snapshot)

    resolution = route_index.resolve_message_route("牛牛帮助 复读")
    assert resolution.index_hit is True
    assert resolution.matched_modules == frozenset({"help"})

    resolution = route_index.resolve_message_route("牛牛轮盘")
    assert resolution.matched_modules == frozenset({"roulette"})

    resolution = route_index.resolve_message_route("八角笼牛")
    assert resolution.matched_modules == frozenset({"duel"})


def test_event_command_traffic_uses_index_before_legacy(monkeypatch: pytest.MonkeyPatch) -> None:
    event = MagicMock()
    event.get_plaintext.return_value = "今天天气不错"
    resolution = route_index.RouteResolution(frozenset(), False)

    monkeypatch.setattr(activation, "route_index_strict", lambda: False)
    monkeypatch.setattr(activation, "legacy_command_traffic", lambda _plain: False)

    assert activation.event_command_traffic(event, {}, resolution=resolution) is False

    resolution = route_index.RouteResolution(frozenset({"help"}), True)
    assert activation.event_command_traffic(event, {}, resolution=resolution) is True


def test_select_priority_matchers_filters_chatter_by_index(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(activation, "route_index_enabled", lambda: True)
    monkeypatch.setattr(activation, "matcher_is_command_only", lambda matcher: matcher is _CommandMatcher)

    snapshot = route_index.RouteIndexSnapshot(
        prefix_to_modules={"牛牛帮助": frozenset({"help"})},
        exact_to_modules={},
        regex_entries=(),
        always_run_modules=frozenset(),
        passive_modules=frozenset({"repeater"}),
        indexed_modules=frozenset({"help", "duel"}),
    )
    monkeypatch.setattr(activation, "get_route_index", lambda: snapshot)

    resolution = route_index.RouteResolution(frozenset(), True)
    selected = activation.select_priority_matchers(
        [_CommandMatcher, _PassiveMatcher, _HelpMatcher, _DuelMatcher],
        command_traffic=False,
        resolution=resolution,
    )

    assert _CommandMatcher not in selected
    assert _PassiveMatcher in selected
    assert _HelpMatcher not in selected
    assert _DuelMatcher not in selected


def test_select_priority_matchers_keeps_block_and_passive_on_command(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(activation, "route_index_enabled", lambda: True)

    snapshot = route_index.RouteIndexSnapshot(
        prefix_to_modules={"牛牛帮助": frozenset({"help"})},
        exact_to_modules={},
        regex_entries=(),
        always_run_modules=frozenset(),
        passive_modules=frozenset({"repeater"}),
        indexed_modules=frozenset({"help", "duel"}),
    )
    monkeypatch.setattr(activation, "get_route_index", lambda: snapshot)

    resolution = route_index.RouteResolution(frozenset({"help"}), True)
    selected = activation.select_priority_matchers(
        [_PassiveMatcher, _BlockMatcher, _HelpMatcher, _DuelMatcher],
        command_traffic=True,
        resolution=resolution,
    )

    assert _PassiveMatcher in selected
    assert _BlockMatcher in selected
    assert _HelpMatcher in selected
    assert _DuelMatcher not in selected


def test_select_priority_matchers_safe_mode_fallback_without_index_hit(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(activation, "route_index_enabled", lambda: True)
    monkeypatch.setattr(activation, "route_index_strict", lambda: False)
    monkeypatch.setattr(activation, "matcher_is_command_only", lambda matcher: matcher is _CommandMatcher)

    resolution = route_index.RouteResolution(frozenset(), False)
    pool = [_CommandMatcher, _PassiveMatcher]
    selected = activation.select_priority_matchers(pool, command_traffic=True, resolution=resolution)
    assert selected == pool

    selected = activation.select_priority_matchers(pool, command_traffic=False, resolution=resolution)
    assert _CommandMatcher not in selected
    assert _PassiveMatcher in selected
