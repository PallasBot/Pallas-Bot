"""从消息正文解析牛牛帮助 / 开关命令参数"""

from __future__ import annotations

import re

from pallas.core.foundation.command_prefix import extract_command_tail

HELP_COMMAND = "牛牛帮助"
PLUGIN_ENABLE_COMMAND = "牛牛开启"
PLUGIN_DISABLE_COMMAND = "牛牛关闭"
PLUGIN_ENABLE_ALL_COMMAND = "牛牛开启全部功能"
PLUGIN_DISABLE_ALL_COMMAND = "牛牛关闭全部功能"

_TAIL_WS_RE = re.compile(r"[\s\u3000]+")


def extract_help_tail(plaintext: str) -> str:
    return extract_command_tail(plaintext, HELP_COMMAND)


def parse_command_args(
    plaintext: str,
    command: str,
    *,
    plugin_count: int | None = None,
    allow_function_split: bool = False,
) -> list[str]:
    """
    解析命令参数。

    - 有空格：按空白拆分。
    - 无空格：连写解析。
    """
    rest = extract_command_tail(plaintext, command)
    if not rest:
        return []
    if _TAIL_WS_RE.search(rest):
        return [part for part in _TAIL_WS_RE.split(rest) if part]
    return _parse_compact_tail(
        rest,
        plugin_count=plugin_count,
        allow_function_split=allow_function_split,
    )


def parse_help_args(plaintext: str, *, plugin_count: int | None = None) -> list[str]:
    return parse_command_args(
        plaintext,
        HELP_COMMAND,
        plugin_count=plugin_count,
        allow_function_split=True,
    )


def parse_plugin_toggle_args(
    plaintext: str,
    command: str,
    *,
    plugin_count: int | None = None,
) -> list[str]:
    if command not in (PLUGIN_ENABLE_COMMAND, PLUGIN_DISABLE_COMMAND):
        raise ValueError(f"unsupported toggle command: {command}")
    return parse_command_args(
        plaintext,
        command,
        plugin_count=plugin_count,
        allow_function_split=False,
    )


def _parse_compact_tail(
    rest: str,
    *,
    plugin_count: int | None,
    allow_function_split: bool,
) -> list[str]:
    match = re.match(r"^(\d+)(.*)$", rest)
    if not match:
        return [rest]

    plugin_part, tail = match.group(1), match.group(2)
    if not tail:
        return _split_compact_digits(
            plugin_part,
            plugin_count=plugin_count,
            allow_function_split=allow_function_split,
        )

    if tail.isdigit():
        if allow_function_split:
            return [plugin_part, tail]
        return [rest]

    if plugin_count is not None and _is_valid_plugin_index(plugin_part, plugin_count):
        return [plugin_part, tail]

    return [rest]


def _split_compact_digits(
    digits: str,
    *,
    plugin_count: int | None,
    allow_function_split: bool,
) -> list[str]:
    if plugin_count is not None and _is_valid_plugin_index(digits, plugin_count):
        return [digits]

    if allow_function_split and plugin_count is not None and len(digits) >= 2:
        for i in range(1, len(digits)):
            plugin_part, func_part = digits[:i], digits[i:]
            if not func_part.isdigit():
                continue
            if _is_valid_plugin_index(plugin_part, plugin_count):
                return [plugin_part, func_part]

    return [digits]


def _is_valid_plugin_index(index_text: str, plugin_count: int) -> bool:
    if not index_text.isdigit() or plugin_count <= 0:
        return False
    index = int(index_text)
    return 1 <= index <= plugin_count
