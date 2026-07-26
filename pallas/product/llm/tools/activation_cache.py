"""跨轮保留工具发现结果。"""

from __future__ import annotations

import time

_TTL_SEC = 600.0
_cache: dict[tuple[int, int | None, int], tuple[float, tuple[str, ...]]] = {}


def activated_tool_names(bot_id: int, group_id: int | None, user_id: int) -> list[str]:
    key = (int(bot_id), int(group_id) if group_id is not None else None, int(user_id))
    row = _cache.get(key)
    if row is None:
        return []
    expires_at, names = row
    if expires_at <= time.monotonic():
        _cache.pop(key, None)
        return []
    return list(names)


def remember_activated_tools(bot_id: int, group_id: int | None, user_id: int, names: list[str]) -> None:
    key = (int(bot_id), int(group_id) if group_id is not None else None, int(user_id))
    existing = activated_tool_names(*key)
    merged = tuple(dict.fromkeys([*existing, *(str(name).strip() for name in names if str(name).strip())]))
    if merged:
        _cache[key] = (time.monotonic() + _TTL_SEC, merged)


def clear_activation_cache_for_tests() -> None:
    _cache.clear()
