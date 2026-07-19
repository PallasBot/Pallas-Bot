"""coord 待处理快照。"""

from __future__ import annotations

import time
from typing import Any

from pallas.core.platform.coord.redis_settings import coord_redis_enabled
from pallas.core.platform.shard.coord.coord_redis_store import read_json_sync, scan_keys_sync

_COORD_PREFIXES = {
    "bot_action": "pallas:coord:bot_action:",
    "bot_count": "pallas:coord:bot_count:",
    "cage_duel": "pallas:coord:cage_duel:",
    "duel_group": "pallas:coord:duel_group:",
    "spy_group": "pallas:coord:spy_group:",
    "group_gate": "pallas:coord:group_gate:",
    "maa_pending": "pallas:coord:maa_pending:",
    "maa_route": "pallas:coord:maa_route:",
    "maa_seen": "pallas:coord:maa_seen:",
    "repeater_buffer": "pallas:coord:repeater_buffer:",
    "repeater_reply_buffer": "pallas:coord:repeater_reply_buffer:",
    "duel_qte_session": "pallas:duel_qte:session:",
    "duel_qte_greeting": "pallas:duel_qte:greeting_users:",
    "ai_task": "pallas:ai_task:",
}


def _empty_snapshot(*, scan_skipped: bool) -> dict[str, Any]:
    return {
        "storage": "redis",
        "total_json": 0,
        "actionable_total": 0,
        "historical_retained": 0,
        "by_dir": dict.fromkeys(_COORD_PREFIXES, 0),
        "bot_action_open": 0,
        "bot_action_stale_open": 0,
        "scan_skipped": scan_skipped,
    }


def coord_pending_snapshot_sync(*, live: bool = False) -> dict[str, Any]:
    if not coord_redis_enabled():
        return _empty_snapshot(scan_skipped=False)
    if not live:
        return _empty_snapshot(scan_skipped=True)

    total_json = 0
    actionable_total = 0
    historical_retained = 0
    bot_action_open = 0
    bot_action_stale_open = 0
    now = time.time()
    by_dir = dict.fromkeys(_COORD_PREFIXES, 0)

    for name, prefix in _COORD_PREFIXES.items():
        keys = scan_keys_sync(prefix)
        by_dir[name] = len(keys)
        total_json += len(keys)
        if name != "bot_action":
            continue
        for key in keys:
            data = read_json_sync(key) or {}
            if data.get("done"):
                historical_retained += 1
                continue
            bot_action_open += 1
            actionable_total += 1
            deadline = float(data.get("deadline") or 0)
            if deadline > 0 and deadline < now:
                bot_action_stale_open += 1

    return {
        "storage": "redis",
        "total_json": total_json,
        "actionable_total": actionable_total,
        "historical_retained": historical_retained,
        "by_dir": by_dir,
        "bot_action_open": bot_action_open,
        "bot_action_stale_open": bot_action_stale_open,
        "scan_skipped": False,
    }
