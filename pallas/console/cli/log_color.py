"""实时日志终端染色：复用 Bot 控制台同款配色（时间绿、级别按 loguru 色板、来源按通道色板）。"""

from __future__ import annotations

import os
import re
import sys

_RESET = "\x1b[0m"
_GREEN = "\x1b[32m"

_LEVEL_COLORS = {
    "TRACE": "\x1b[37m",
    "DEBUG": "\x1b[36m",
    "INFO": "\x1b[32m",
    "SUCCESS": "\x1b[32m",
    "WARNING": "\x1b[33m",
    "ERROR": "\x1b[31m",
    "CRITICAL": "\x1b[31m",
}

_SOURCE_COLORS = (
    "\x1b[96m",
    "\x1b[93m",
    "\x1b[95m",
    "\x1b[92m",
    "\x1b[94m",
    "\x1b[97m",
    "\x1b[91m",
)

_LEVEL_RE = re.compile(r"\[(TRACE|DEBUG|INFO|SUCCESS|WARNING|ERROR|CRITICAL)[ ]*\]", re.IGNORECASE)
_TIME_RE = re.compile(r"^\d{2}-\d{2} \d{2}:\d{2}:\d{2}")


def color_enabled() -> bool:
    return sys.stdout.isatty() and os.environ.get("NO_COLOR") is None


def colorize_source(label: str) -> str:
    """来源标签染色（同一标签颜色稳定）。"""
    if not color_enabled():
        return label
    index = sum(map(ord, label)) % len(_SOURCE_COLORS)
    return f"{_SOURCE_COLORS[index]}{label}{_RESET}"


def colorize_line(line: str) -> str:
    """按 Bot 控制台配色给单行日志染色：时间绿、级别按 loguru 色板。"""
    if not color_enabled():
        return line

    def _level(match: re.Match) -> str:
        code = _LEVEL_COLORS.get(match.group(1).upper())
        return f"{code}{match.group(0)}{_RESET}" if code else match.group(0)

    colored = _LEVEL_RE.sub(_level, line)
    time_match = _TIME_RE.match(colored)
    if time_match:
        colored = f"{_GREEN}{time_match.group(0)}{_RESET}{colored[time_match.end() :]}"
    return colored
