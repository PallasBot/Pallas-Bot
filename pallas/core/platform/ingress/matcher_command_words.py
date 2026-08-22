"""从已加载 matcher 提取命令字（主命令 + 别名），供命令车道与联邦能力复用。

menu_data / extra.command_prefixes 未必覆盖 on_command 的 aliases 与 on_alconna
的 shortcut 别名，这里直接从 nonebot matcher 的 rule checker 提取补齐盲区。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from nonebot.matcher import matchers
from nonebot.rule import CommandRule, ShellCommandRule

if TYPE_CHECKING:
    from collections.abc import Iterable

    from nonebot.matcher import Matcher

_COMMAND_CHECKERS = frozenset({CommandRule, ShellCommandRule})

_MIN_COMMAND_WORD_LEN = 2

_SEP_CACHE: str | None = None


def _command_sep() -> str:
    """NoneBot 多段命令的连接分隔符（读自配置，缺省回退 ``/``）。"""
    global _SEP_CACHE
    if _SEP_CACHE is not None:
        return _SEP_CACHE
    sep = "/"
    try:
        from nonebot import get_driver

        raw = getattr(get_driver().config, "command_sep", None)
        if raw:
            sep = str(next(iter(raw)) or "/")
    except Exception:
        pass
    _SEP_CACHE = sep
    return sep


def clear_command_sep_cache() -> None:
    global _SEP_CACHE
    _SEP_CACHE = None


def _collect_command_call_words(call: object, words: set[str]) -> None:
    if type(call) in _COMMAND_CHECKERS:
        cmds = getattr(call, "cmds", None)
        if not cmds:
            return
        for cmd in cmds:
            if not cmd:
                continue
            word = _command_sep().join(str(part) for part in cmd if str(part or "").strip()).strip()
            if len(word) >= _MIN_COMMAND_WORD_LEN:
                words.add(word)
        return
    if type(call).__name__ != "AlconnaRule":
        return
    try:
        command = getattr(call, "command", None)
        cmd = command() if callable(command) else None
        if cmd is None:
            return
        from arclet.alconna.manager import command_manager

        main = getattr(cmd, "command", None)
        if main:
            text = str(main).strip()
            if len(text) >= _MIN_COMMAND_WORD_LEN:
                words.add(text)
        try:
            shortcuts = command_manager.get_shortcut(cmd)
        except Exception:
            return
        for alias in shortcuts:
            text = str(alias or "").strip()
            if len(text) >= _MIN_COMMAND_WORD_LEN:
                words.add(text)
    except Exception:
        return


def collect_command_words_for_matcher(matcher: type[Matcher]) -> tuple[str, ...]:
    """收集单个 matcher 的命令字与别名（on_command + on_alconna）。"""
    from pallas.core.platform.ingress.matcher_activation import iter_matcher_checker_calls

    words: set[str] = set()
    for call in iter_matcher_checker_calls(matcher):
        _collect_command_call_words(call, words)
    return tuple(sorted(words))


def collect_command_words_from_matchers(matchers_iter: Iterable[type[Matcher]] | None = None) -> tuple[str, ...]:
    """遍历已加载 matcher，收集主命令字与别名（on_command + on_alconna）。

    ``matchers_iter`` 缺省时遍历 nonebot 全局 ``matchers`` 注册表。
    """
    words: set[str] = set()
    if matchers_iter is None:
        for priority_matchers in matchers.values():
            for matcher in priority_matchers:
                words.update(collect_command_words_for_matcher(matcher))
    else:
        for matcher in matchers_iter:
            words.update(collect_command_words_for_matcher(matcher))
    return tuple(sorted(words))
