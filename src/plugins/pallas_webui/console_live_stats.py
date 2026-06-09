"""单进程控制台指标快照（重启恢复当日收/发、Matcher 分项与耗时日志）。"""

from __future__ import annotations

import json
import os
import time
from typing import Any

from src.foundation.paths import plugin_data_dir
from src.plugins.pallas_webui.daily_stats_store import interprocess_stats_lock

_STORE_VER = 1


def live_stats_path():
    return plugin_data_dir("pallas_webui") / "console_live_stats.json"


def _read_raw() -> dict[str, Any]:
    p = live_stats_path()
    if not p.is_file():
        return {"v": _STORE_VER, "bots": {}}
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"v": _STORE_VER, "bots": {}}
    if not isinstance(raw, dict):
        return {"v": _STORE_VER, "bots": {}}
    bots = raw.get("bots")
    if not isinstance(bots, dict):
        raw["bots"] = {}
    raw.setdefault("v", _STORE_VER)
    return raw


def read_bots_for_boot() -> dict[str, dict[str, Any]]:
    bots = _read_raw().get("bots")
    if not isinstance(bots, dict):
        return {}
    return {str(k): v for k, v in bots.items() if isinstance(v, dict)}


def preserve_matcher_hist_from_disk(bots: dict[str, Any]) -> dict[str, Any]:
    old_bots = _read_raw().get("bots")
    if not isinstance(old_bots, dict):
        return bots
    merged: dict[str, Any] = {}
    for sid, rec in bots.items():
        row = dict(rec) if isinstance(rec, dict) else {}
        prev = old_bots.get(sid)
        if isinstance(prev, dict):
            hist = prev.get("matcher_hist")
            if isinstance(hist, list) and hist:
                row["matcher_hist"] = hist
        merged[str(sid)] = row
    return merged


def write_bots_sync(bots: dict[str, Any], *, preserve_matcher_hist: bool = False) -> bool:
    payload = preserve_matcher_hist_from_disk(bots) if preserve_matcher_hist else bots
    current = _read_raw()
    if current.get("bots") == payload:
        return False
    data: dict[str, Any] = {
        "v": _STORE_VER,
        "updated_at": time.time(),
        "bots": payload,
    }
    p = live_stats_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(f"{p.stem}.{os.getpid()}.tmp")
    body = json.dumps(data, ensure_ascii=False, indent=2)
    with interprocess_stats_lock():
        try:
            tmp.write_text(body, encoding="utf-8")
            tmp.replace(p)
        finally:
            try:
                tmp.unlink(missing_ok=True)
            except OSError:
                pass
    return True
