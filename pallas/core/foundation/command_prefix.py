"""消息正文命令前缀：去 command_start、大小写不敏感匹配。"""

from __future__ import annotations


def strip_leading_command_marks(text: str) -> str:
    """去掉 NoneBot ``command_start`` 与遗留 ``/`` 前缀。"""
    stripped = (text or "").strip()
    starts: tuple[str, ...] = ("/", "")
    try:
        from nonebot import get_driver

        raw = get_driver().config.command_start
        if raw:
            starts = tuple(str(s) for s in raw)
    except Exception:
        pass
    for start in sorted((s for s in starts if s), key=len, reverse=True):
        if stripped.startswith(start):
            return stripped[len(start) :].lstrip()
    if stripped.startswith("/"):
        return stripped[1:].lstrip()
    return stripped


def matches_command_prefix(plaintext: str, command: str) -> bool:
    """命令前缀是否匹配。"""
    text = strip_leading_command_marks(plaintext)
    cmd = (command or "").strip()
    if not cmd or len(text) < len(cmd):
        return False
    return text[: len(cmd)].casefold() == cmd.casefold()


def matches_text_prefix(text: str, prefix: str) -> bool:
    """行内固定前缀是否匹配。"""
    t = (text or "").strip()
    p = (prefix or "").strip()
    if not p or len(t) < len(p):
        return False
    return t[: len(p)].casefold() == p.casefold()


def peel_text_prefix(text: str, prefix: str) -> str:
    """去掉行内前缀并返回剩余文本；不匹配则返回空串。"""
    t = (text or "").strip()
    p = (prefix or "").strip()
    if not matches_text_prefix(t, p):
        return ""
    return t[len(p) :].lstrip()


def extract_command_tail(plaintext: str, command: str) -> str:
    """去掉单条命令前缀，返回剩余文本。"""
    text = strip_leading_command_marks(plaintext)
    cmd = (command or "").strip()
    if not cmd or len(text) < len(cmd):
        return ""
    if text[: len(cmd)].casefold() != cmd.casefold():
        return ""
    return text[len(cmd) :].lstrip()


def extract_command_tail_any(plaintext: str, *commands: str) -> str:
    """按长度优先匹配多条命令前缀之一。"""
    text = strip_leading_command_marks(plaintext)
    for cmd in sorted((c.strip() for c in commands if c and c.strip()), key=len, reverse=True):
        if len(text) < len(cmd):
            continue
        if text[: len(cmd)].casefold() != cmd.casefold():
            continue
        return text[len(cmd) :].lstrip()
    return ""
