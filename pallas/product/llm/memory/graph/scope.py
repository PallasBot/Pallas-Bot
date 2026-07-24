"""记忆图谱 scope_key 约定：bot:{bot_id}:group:{group_id}。"""

from __future__ import annotations

import re

from pallas.product.llm.session_models import normalize_group_scope

_SCOPE_RE = re.compile(r"^bot:(?P<bot>\d+):group:(?P<group>\d+)$")


def make_scope_key(*, bot_id: int, group_id: int | None) -> str:
    return f"bot:{int(bot_id)}:group:{normalize_group_scope(group_id)}"


def parse_scope_key(scope_key: str) -> tuple[int | None, int | None]:
    text = str(scope_key or "").strip()
    match = _SCOPE_RE.match(text)
    if not match:
        return None, None
    return int(match.group("bot")), int(match.group("group"))


def resolve_scope(
    *,
    bot_id: int | None = None,
    group_id: int | None = None,
    scope_key: str | None = None,
) -> tuple[str, int, int]:
    """返回 (scope_key, bot_id, group_id)。优先解析 scope_key，否则用 bot/group。"""
    raw = str(scope_key or "").strip()
    if raw:
        parsed_bot, parsed_group = parse_scope_key(raw)
        if parsed_bot is None:
            raise ValueError(f"invalid scope_key: {raw}")
        return make_scope_key(bot_id=parsed_bot, group_id=parsed_group), parsed_bot, int(parsed_group or 0)
    if bot_id is None or int(bot_id) <= 0:
        raise ValueError("bot_id required")
    gid = normalize_group_scope(group_id)
    return make_scope_key(bot_id=int(bot_id), group_id=gid), int(bot_id), gid
