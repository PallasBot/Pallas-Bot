from types import SimpleNamespace

from packages.help.plugin_detail_data import (
    command_match_tokens,
    normalize_plugin_usage_text,
    search_command_help_targets,
)


def test_normalize_plugin_usage_text_numbered() -> None:
    raw = "1. 牛牛帮助 — 总览\n2. 牛牛帮助 1 — 详情"
    out = normalize_plugin_usage_text(raw)
    assert out.startswith("1. ")
    assert "2. " in out


def test_normalize_plugin_usage_text_dot_separator() -> None:
    out = normalize_plugin_usage_text("牛牛帮助 · 牛牛帮助 1 · 牛牛开启")
    assert out.splitlines()[0].startswith("1. ")
    assert len(out.splitlines()) == 3


def _make_plugin(name: str, menu_data: list[dict], *, display: str | None = None):
    return SimpleNamespace(
        name=name,
        metadata=SimpleNamespace(name=display or name, extra={"menu_data": menu_data}),
    )


def test_command_match_tokens_splits_alternatives_and_drops_placeholders() -> None:
    tokens = command_match_tokens({"func": "牛牛喝酒", "trigger_condition": "牛牛喝酒 / 牛牛干杯 / 牛牛继续喝"})
    assert tokens == ["牛牛喝酒", "牛牛喝酒", "牛牛干杯", "牛牛继续喝"]

    placeholder = command_match_tokens({"func": "牛牛拉黑", "trigger_condition": "牛牛拉黑 / 牛牛屏蔽 + QQ 或 @"})
    assert placeholder == ["牛牛拉黑", "牛牛拉黑", "牛牛屏蔽"]

    bracketed = command_match_tokens({"func": "同意好友", "trigger_condition": "同意好友 <QQ号>"})
    assert bracketed == ["同意好友"]


def test_search_command_help_targets_exact_by_func() -> None:
    plugins = [
        _make_plugin(
            "drink",
            [{"func": "牛牛喝酒", "trigger_condition": "牛牛喝酒 / 牛牛干杯"}],
            display="喝酒",
        )
    ]
    targets = search_command_help_targets("牛牛喝酒", plugins)
    assert len(targets) == 1
    assert targets[0].plugin_name == "drink"
    assert targets[0].func_name == "牛牛喝酒"
    assert targets[0].plugin_display == "喝酒"


def test_search_command_help_targets_matches_trigger_alias() -> None:
    plugins = [_make_plugin("drink", [{"func": "牛牛喝酒", "trigger_condition": "牛牛喝酒 / 牛牛干杯"}])]
    targets = search_command_help_targets("牛牛干杯", plugins)
    assert len(targets) == 1
    assert targets[0].func_name == "牛牛喝酒"


def test_search_command_help_targets_substring_fallback() -> None:
    plugins = [_make_plugin("drink", [{"func": "牛牛喝酒", "trigger_condition": "牛牛喝酒 / 牛牛干杯"}])]
    targets = search_command_help_targets("喝酒", plugins)
    assert len(targets) == 1
    assert targets[0].func_name == "牛牛喝酒"


def test_search_command_help_targets_exact_beats_substring() -> None:
    plugins = [
        _make_plugin("drink", [{"func": "牛牛喝酒", "trigger_condition": "牛牛喝酒"}]),
        _make_plugin("sober", [{"func": "牛牛喝酒醒酒", "trigger_condition": "牛牛喝酒醒酒"}]),
    ]
    targets = search_command_help_targets("牛牛喝酒", plugins)
    assert [(t.plugin_name, t.func_name) for t in targets] == [("drink", "牛牛喝酒")]


def test_search_command_help_targets_multiple_candidates() -> None:
    plugins = [
        _make_plugin("a", [{"func": "牛牛签到", "trigger_condition": "牛牛签到"}]),
        _make_plugin("b", [{"func": "牛牛签到提醒", "trigger_condition": "牛牛签到提醒"}]),
    ]
    targets = search_command_help_targets("牛牛签到", plugins)
    # 「牛牛签到」对 a 精确、对 b 子串；精确优先只返回 a
    assert [(t.plugin_name, t.func_name) for t in targets] == [("a", "牛牛签到")]

    targets2 = search_command_help_targets("签到", plugins)
    assert {t.plugin_name for t in targets2} == {"a", "b"}


def test_search_command_help_targets_no_match() -> None:
    plugins = [_make_plugin("drink", [{"func": "牛牛喝酒", "trigger_condition": "牛牛喝酒"}])]
    assert search_command_help_targets("不存在的口令", plugins) == []
