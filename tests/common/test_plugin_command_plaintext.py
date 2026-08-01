from __future__ import annotations

from types import SimpleNamespace

from pallas.core.platform.ingress.plugin_command_plaintext import (
    clear_plugin_command_plaintext_cache,
    extract_command_prefixes_from_menu_data,
    is_plugin_command_plaintext,
)


def test_extract_command_prefixes_from_menu_data_skips_chat_like_trigger() -> None:
    menu_data = [
        {"trigger_condition": "@牛牛 / 牛牛 + 文本"},
        {"trigger_condition": "牛牛唱歌 歌曲名 [key=±N]"},
        {"trigger_condition": "牛牛继续唱 / 牛牛接着唱"},
        {"trigger_condition": "决斗事件重载"},
    ]

    prefixes = extract_command_prefixes_from_menu_data(menu_data)

    assert "牛牛" not in prefixes
    assert "牛牛唱歌" in prefixes
    assert "牛牛继续唱" in prefixes
    assert "牛牛接着唱" in prefixes
    assert "决斗事件重载" in prefixes


def test_extract_command_prefixes_keeps_command_before_plus_args() -> None:
    menu_data = [
        {"trigger_condition": "牛牛表情列表 / 表情包制作"},
        {"trigger_condition": "牛牛表情搜索 + 关键词"},
        {"trigger_condition": "牛牛表情详情 + 关键词"},
        {"trigger_condition": "牛牛表情推荐 + 意图"},
        {"trigger_condition": "牛牛表情 + 关键词 + 图片/文字"},
        {"trigger_condition": "牛牛拉黑 / 牛牛屏蔽 / 牛牛解禁 + QQ 或 @"},
    ]

    prefixes = extract_command_prefixes_from_menu_data(menu_data)

    assert "牛牛表情列表" in prefixes
    assert "表情包制作" in prefixes
    assert "牛牛表情搜索" in prefixes
    assert "牛牛表情详情" in prefixes
    assert "牛牛表情推荐" in prefixes
    assert "牛牛表情" in prefixes
    assert "牛牛拉黑" in prefixes
    assert "牛牛屏蔽" in prefixes
    assert "牛牛解禁" in prefixes
    assert "文字" not in prefixes
    assert "关键词" not in prefixes
    assert "牛牛" not in prefixes


def test_is_plugin_command_plaintext_uses_trie_and_menu_prefixes(monkeypatch) -> None:
    fake_plugins = [
        SimpleNamespace(
            metadata=SimpleNamespace(
                extra={
                    "menu_data": [
                        {"trigger_condition": "牛牛唱歌 歌曲名 [key=±N]"},
                        {"trigger_condition": "牛牛点歌 歌曲名"},
                        {"trigger_condition": "牛牛MAA状态"},
                    ]
                }
            )
        )
    ]
    monkeypatch.setattr(
        "pallas.core.platform.ingress.plugin_command_plaintext.get_loaded_plugins",
        lambda: fake_plugins,
    )
    monkeypatch.setattr(
        "pallas.core.platform.ingress.plugin_command_plaintext.TrieRule.prefix.longest_prefix",
        lambda text: SimpleNamespace(key="牛牛画画") if text.startswith("牛牛画画") else None,
    )
    clear_plugin_command_plaintext_cache()

    assert is_plugin_command_plaintext("牛牛画画")
    assert is_plugin_command_plaintext("牛牛唱歌 海阔天空")
    assert is_plugin_command_plaintext("牛牛点歌 晴天")
    assert is_plugin_command_plaintext("牛牛MAA状态")
    assert not is_plugin_command_plaintext("牛牛 今天吃什么")


def test_is_plugin_command_plaintext_uses_explicit_command_prefixes(monkeypatch) -> None:
    fake_plugins = [
        SimpleNamespace(
            metadata=SimpleNamespace(
                extra={
                    "command_prefixes": ["一歌唱歌", "一歌点歌"],
                    "menu_data": [
                        {"trigger_condition": "牛牛唱歌 歌曲名 [key=±N]"},
                    ],
                }
            )
        )
    ]
    monkeypatch.setattr(
        "pallas.core.platform.ingress.plugin_command_plaintext.get_loaded_plugins",
        lambda: fake_plugins,
    )
    monkeypatch.setattr(
        "pallas.core.platform.ingress.plugin_command_plaintext.TrieRule.prefix.longest_prefix",
        lambda _text: None,
    )
    clear_plugin_command_plaintext_cache()

    assert is_plugin_command_plaintext("一歌唱歌 皆大欢喜")
    assert is_plugin_command_plaintext("一歌点歌")
    assert is_plugin_command_plaintext("牛牛唱歌 海阔天空")
    assert not is_plugin_command_plaintext("一歌随便聊")


def test_is_plugin_command_plaintext_builds_plugin_prefix_cache_once(monkeypatch) -> None:
    fake_plugins = [
        SimpleNamespace(
            metadata=SimpleNamespace(
                extra={
                    "menu_data": [
                        {"trigger_condition": "牛牛唱歌 歌曲名 [key=±N]"},
                    ]
                }
            )
        )
    ]
    load_count = 0

    def fake_loaded_plugins():
        nonlocal load_count
        load_count += 1
        return fake_plugins

    monkeypatch.setattr(
        "pallas.core.platform.ingress.plugin_command_plaintext.get_loaded_plugins",
        fake_loaded_plugins,
    )
    monkeypatch.setattr(
        "pallas.core.platform.ingress.plugin_command_plaintext.TrieRule.prefix.longest_prefix",
        lambda _text: None,
    )
    clear_plugin_command_plaintext_cache()

    assert is_plugin_command_plaintext("牛牛唱歌 海阔天空")
    assert is_plugin_command_plaintext("牛牛唱歌 晴天")
    assert load_count == 1
