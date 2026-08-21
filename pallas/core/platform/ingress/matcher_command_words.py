"""从已加载 matcher 提取命令字（主命令 + 别名），供命令车道与联邦能力复用。

menu_data / extra.command_prefixes 未必覆盖 on_command 的 aliases 与 on_alconna
的 shortcut 别名，这里直接从 nonebot matcher 的 rule checker 提取补齐盲区。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from nonebot.matcher import matchers
from nonebot.rule import CommandRule, ShellCommandRule

if TYPE_CHECKING:
    from nonebot.matcher import Matcher

_COMMAND_CHECKERS = frozenset({CommandRule, ShellCommandRule})


def _matcher_calls(matcher: type[Matcher]):
    checkers = tuple(getattr(getattr(matcher, "rule", None), "checkers", ()))
    for checker in checkers:
        call = getattr(checker, "call", None)
        if call is None:
            continue
        nested = getattr(call, "checkers", None)
        if nested:
            for inner in nested:
                inner_call = getattr(inner, "call", None)
                if inner_call is not None:
                    yield inner_call
            continue
        yield call


def _collect_command_call_words(call: object, words: set[str]) -> None:
    if type(call) in _COMMAND_CHECKERS:
        cmds = getattr(call, "cmds", None)
        if not cmds:
            return
        for cmd in cmds:
            if not cmd:
                continue
            word = str(cmd[0] if len(cmd) == 1 else " ".join(cmd)).strip()
            if word:
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
            words.add(str(main).strip())
        try:
            shortcuts = command_manager.get_shortcut(cmd)
        except Exception:
            return
        for alias in shortcuts:
            text = str(alias or "").strip()
            if text:
                words.add(text)
    except Exception:
        return


def collect_command_words_from_matchers() -> tuple[str, ...]:
    """遍历已加载 matcher，收集主命令字与别名（on_command + on_alconna）。"""
    words: set[str] = set()
    for priority_matchers in matchers.values():
        for matcher in priority_matchers:
            for call in _matcher_calls(matcher):
                _collect_command_call_words(call, words)
    return tuple(sorted(words))
