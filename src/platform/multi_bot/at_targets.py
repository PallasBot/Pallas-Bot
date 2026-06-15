"""群消息 @ 目标解析。"""

from __future__ import annotations

import re

from src.platform.multi_bot.fleet import get_fleet_bot_ids

_AT_QQ_RE = re.compile(r"\[(?:CQ:)?at(?:,qq=|:qq=)(\d+)")


def group_at_qq_ids(event) -> frozenset[int]:
    out: set[int] = set()
    message = getattr(event, "message", None)
    if message is not None:
        for seg in message:
            if seg.type != "at":
                continue
            qq = seg.data.get("qq")
            if qq is None or str(qq) in ("all", "0"):
                continue
            try:
                out.add(int(qq))
            except (TypeError, ValueError):
                continue
    if out:
        return frozenset(out)
    raw_message = getattr(event, "raw_message", None) or ""
    for match in _AT_QQ_RE.finditer(raw_message):
        try:
            out.add(int(match.group(1)))
        except (TypeError, ValueError):
            continue
    return frozenset(out)


def message_at_fleet_bot(event) -> bool:
    fleet = get_fleet_bot_ids()
    if not fleet:
        return False
    return bool(group_at_qq_ids(event) & fleet)
