"""群临时会话上下文：SnowLuma 常只上报 sub_type=group 不带 group_id，用近期群消息推断。"""

from __future__ import annotations

import time

# (bot_id, user_id) -> (group_id, monotonic_ts)
_recent_user_group: dict[tuple[str, str], tuple[int, float]] = {}

DEFAULT_INFER_TTL_SEC = 6 * 3600


def record_user_group_activity(
    bot_id: str,
    user_id: str,
    group_id: int,
    *,
    now: float | None = None,
) -> None:
    gid = int(group_id)
    uid = str(user_id).strip()
    bid = str(bot_id).strip()
    if not bid or not uid or gid <= 0:
        return
    ts = time.monotonic() if now is None else float(now)
    _recent_user_group[(bid, uid)] = (gid, ts)


def resolve_inferred_group_id(
    bot_id: str,
    user_id: str,
    *,
    ttl_sec: float = DEFAULT_INFER_TTL_SEC,
    now: float | None = None,
) -> int | None:
    bid = str(bot_id).strip()
    uid = str(user_id).strip()
    if not bid or not uid:
        return None
    entry = _recent_user_group.get((bid, uid))
    if entry is None:
        return None
    gid, ts = entry
    clock = time.monotonic() if now is None else float(now)
    if clock - ts > max(1.0, float(ttl_sec)):
        _recent_user_group.pop((bid, uid), None)
        return None
    return gid if gid > 0 else None


def clear_group_temp_context_for_tests() -> None:
    _recent_user_group.clear()
