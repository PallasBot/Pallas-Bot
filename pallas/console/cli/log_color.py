"""实时日志终端染色：复刻 Bot 原生控制台输出——时间绿、级别按 loguru 色板、
display_name 与紧随的业务前缀（如 [Message]/[Reaction]）按 Bot 通道色板同色。"""

from __future__ import annotations

import os
import re
import sys
import zlib

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

# 来源标签色板（区分 --all 下的多路日志）
_SOURCE_COLORS = (
    "\x1b[96m",
    "\x1b[93m",
    "\x1b[95m",
    "\x1b[92m",
    "\x1b[94m",
    "\x1b[97m",
    "\x1b[91m",
)

# 对应 Bot 控制台 _DISPLAY_NAME_COLORS 的 ANSI 码（<le>/<ly>/<lm>/<lr>/<lc>/<lg>/<lw>/<m>）
_DISPLAY_COLORS = (
    "\x1b[91m",
    "\x1b[93m",
    "\x1b[95m",
    "\x1b[91m",
    "\x1b[96m",
    "\x1b[92m",
    "\x1b[97m",
    "\x1b[35m",
)

_LEVEL_RE = re.compile(r"\[(TRACE|DEBUG|INFO|SUCCESS|WARNING|ERROR|CRITICAL)[ ]*\]", re.IGNORECASE)
_TIME_RE = re.compile(r"^\d{2}-\d{2} \d{2}:\d{2}:\d{2}")
_DISPLAY_RE = re.compile(r"\{([^{}]*)\}")
_TAG_RE = re.compile(r"\[([^\[\]]*)\]")


def color_enabled() -> bool:
    return sys.stdout.isatty() and os.environ.get("NO_COLOR") is None


def _stable_color(text: str, colors: tuple[str, ...]) -> str:
    index = zlib.crc32(text.encode("utf-8")) % len(colors)
    return colors[index]


def colorize_source(label: str) -> str:
    """来源标签染色（同一标签颜色稳定）。"""
    if not color_enabled():
        return label
    return f"{_stable_color(label, _SOURCE_COLORS)}{label}{_RESET}"


def colorize_line(line: str) -> str:
    """复刻 Bot 原生控制台输出：时间绿、级别按 loguru 色板、
    display_name 与紧随的业务前缀（[Message]/[Reaction] 等）按通道色板同色。"""
    if not color_enabled():
        return line
    out: list[str] = []
    pos = 0
    time_match = _TIME_RE.match(line)
    if time_match:
        out.append(f"{_GREEN}{time_match.group(0)}{_RESET}")
        pos = time_match.end()
    level_match = _LEVEL_RE.search(line, pos)
    if level_match and line[pos : level_match.start()].strip() == "":
        code = _LEVEL_COLORS.get(level_match.group(1).upper())
        if code:
            out.extend([
                line[pos : level_match.start()],
                f"{code}{level_match.group(0)}{_RESET}",
            ])
            pos = level_match.end()
    display_match = _DISPLAY_RE.search(line, pos)
    if display_match and line[pos : display_match.start()].strip() == "":
        color = _stable_color(display_match.group(1).strip() or "default", _DISPLAY_COLORS)
        out.extend([
            line[pos : display_match.start()],
            f"{color}{display_match.group(0)}{_RESET}",
        ])
        pos = display_match.end()
        tag_match = _TAG_RE.search(line, pos)
        if tag_match and line[pos : tag_match.start()].strip() == "":
            out.extend([
                line[pos : tag_match.start()],
                f"{color}{tag_match.group(0)}{_RESET}",
            ])
            pos = tag_match.end()
    out.append(line[pos:])
    return "".join(out)
