"""matcher 命令字提取：on_command aliases / on_alconna shortcuts 进入命令前缀集。"""

from __future__ import annotations

import pytest
from nonebot.matcher import matchers

from pallas.core.platform.ingress.matcher_command_words import collect_command_words_from_matchers
from pallas.core.platform.ingress.plugin_command_plaintext import (
    clear_plugin_command_plaintext_cache,
    is_group_plugin_command_plaintext,
    is_plugin_command_plaintext,
)

_REGISTERED: list[type] = []


def _register(matcher: type) -> None:
    _REGISTERED.append(matcher)
    priority = int(getattr(matcher, "priority", 0) or 0)
    matchers.setdefault(priority, []).append(matcher)


@pytest.fixture(autouse=True)
def _clean_matcher_words() -> None:
    clear_plugin_command_plaintext_cache()
    yield
    registered = tuple(_REGISTERED)
    _REGISTERED.clear()
    for items in matchers.values():
        items[:] = [m for m in items if m not in registered]
    clear_plugin_command_plaintext_cache()


def test_collect_command_words_from_on_command_aliases() -> None:
    from nonebot.plugin import on_command

    matcher = on_command("投票禁言", aliases={"发起投票", "投票开始"}, priority=5, block=True)
    _register(matcher)

    words = set(collect_command_words_from_matchers())
    assert {"投票禁言", "发起投票", "投票开始"} <= words


def test_collect_command_words_from_on_alconna_shortcuts() -> None:
    from nonebot_plugin_alconna import on_alconna

    matcher = on_alconna("牛牛戳戳", aliases={"牛牛戳一戳", "戳戳"}, priority=4, block=True)
    _register(matcher)
    clear_plugin_command_plaintext_cache()

    words = set(collect_command_words_from_matchers())
    assert {"牛牛戳戳", "牛牛戳一戳", "戳戳"} <= words

    assert is_group_plugin_command_plaintext("牛牛戳戳")
    assert is_group_plugin_command_plaintext("牛牛戳一戳")
    assert is_group_plugin_command_plaintext("戳戳")


def test_group_plaintext_trie_includes_alias_words() -> None:
    from nonebot.plugin import on_command

    matcher = on_command("投票禁言", aliases={"发起投票"}, priority=5, block=True)
    _register(matcher)

    assert is_group_plugin_command_plaintext("发起投票")
    assert is_group_plugin_command_plaintext("投票禁言")
    assert not is_group_plugin_command_plaintext("投票")
    assert is_plugin_command_plaintext("发起投票")
