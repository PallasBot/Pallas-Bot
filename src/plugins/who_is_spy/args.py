from __future__ import annotations

import re

# 「暗牌」= 私聊只发词、不标平民/卧底；与「白板」身份（无词）无关。
_HIDE_ROLE_TOKENS = frozenset({"暗牌", "不标身份", "隐藏身份"})
_SHOW_ROLE_TOKENS = frozenset({"明牌", "标身份", "附带身份"})
_BLANK_TOKEN_RE = re.compile(r"^白板(\d*)$")
_NO_BLANK_TOKENS = frozenset({"无白板", "白板0"})


def parse_start_args(
    text: str,
    *,
    default_undercovers: int,
    default_blanks: int,
    default_show_role: bool,
) -> tuple[int, int, bool]:
    undercover_count = default_undercovers
    blank_count = default_blanks
    show_role = default_show_role
    blank_override = False
    for token in (text or "").split():
        if token in _HIDE_ROLE_TOKENS:
            show_role = False
        elif token in _SHOW_ROLE_TOKENS:
            show_role = True
        elif token in _NO_BLANK_TOKENS:
            blank_count = 0
            blank_override = True
        else:
            blank_match = _BLANK_TOKEN_RE.match(token)
            if blank_match:
                suffix = blank_match.group(1)
                blank_count = int(suffix) if suffix else 1
                blank_override = True
            elif token.isdigit():
                undercover_count = max(1, min(3, int(token)))
    if not blank_override:
        blank_count = default_blanks
    blank_count = max(0, min(2, blank_count))
    return undercover_count, blank_count, show_role


def parse_undercover_count(text: str, *, default: int) -> int:
    undercover_count, _, _ = parse_start_args(
        text,
        default_undercovers=default,
        default_blanks=0,
        default_show_role=False,
    )
    return undercover_count
