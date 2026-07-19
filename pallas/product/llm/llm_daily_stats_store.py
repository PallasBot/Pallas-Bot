"""LLM 任务按自然日汇总持久化（Bot / AI 快照）。"""

from __future__ import annotations

import json
import os
import threading
from datetime import date, timedelta
from operator import itemgetter
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from pathlib import Path

_STORE_VER = 1
_MAX_RETAIN_DAYS = 500
_LOCK = threading.RLock()


def stats_file_path() -> Path:
    from pallas.core.foundation.paths import plugin_data_dir

    return plugin_data_dir("pb_webui", create=True) / "llm_daily_stats.json"


def _read_raw() -> dict[str, Any]:
    p = stats_file_path()
    if not p.exists():
        return {"v": _STORE_VER, "by_day": {}}
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"v": _STORE_VER, "by_day": {}}
    if not isinstance(raw, dict):
        return {"v": _STORE_VER, "by_day": {}}
    raw.setdefault("v", _STORE_VER)
    bd = raw.get("by_day")
    if not isinstance(bd, dict):
        raw["by_day"] = {}
    return raw


def _atomic_write(data: dict[str, Any]) -> None:
    p = stats_file_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(f"{p.stem}.{os.getpid()}.{threading.get_ident()}.tmp")
    payload = json.dumps(data, ensure_ascii=False, indent=2)
    try:
        tmp.write_text(payload, encoding="utf-8")
        tmp.replace(p)
    finally:
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass


def _trim_old_days(by_day: dict[str, Any]) -> None:
    keys = sorted(k for k in by_day if isinstance(k, str) and len(k) >= 10)
    if len(keys) <= _MAX_RETAIN_DAYS:
        return
    for k in keys[: len(keys) - _MAX_RETAIN_DAYS]:
        by_day.pop(k, None)


def merge_side_snapshot(existing: dict[str, Any] | None, snapshot: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(snapshot, dict):
        return existing if isinstance(existing, dict) else {}
    out = dict(existing) if isinstance(existing, dict) else {}
    for key in (
        "source",
        "day_key",
        "updated_at",
        "by_task",
        "totals",
        "tokens",
        "classification",
        "reachable",
    ):
        if key in snapshot:
            out[key] = snapshot[key]
    return out


def write_day_side(day: str, side: str, snapshot: dict[str, Any]) -> None:
    """写入某日 Bot 或 AI 侧快照；side 为 bot / ai。"""
    day_key = str(day).strip()[:10]
    side_key = str(side).strip().lower()
    if len(day_key) < 10 or side_key not in {"bot", "ai"}:
        return
    if not isinstance(snapshot, dict):
        return
    with _LOCK:
        data = _read_raw()
        days = data.setdefault("by_day", {})
        if not isinstance(days, dict):
            data["by_day"] = {}
            days = data["by_day"]
        row = days.setdefault(day_key, {})
        if not isinstance(row, dict):
            days[day_key] = {}
            row = days[day_key]
        prev = row.get(side_key) if isinstance(row.get(side_key), dict) else None
        merged = merge_side_snapshot(prev, snapshot)
        if prev == merged:
            return
        row[side_key] = merged
        _trim_old_days(days)
        _atomic_write(data)


def _parse_iso_day(s: str) -> date | None:
    try:
        return date.fromisoformat(str(s).strip()[:10])
    except ValueError:
        return None


def load_range(*, start_day: str, end_day: str) -> tuple[list[dict[str, Any]], str, str]:
    sd = _parse_iso_day(start_day)
    ed = _parse_iso_day(end_day)
    if sd is None or ed is None:
        return [], start_day[:10], end_day[:10]
    if sd > ed:
        sd, ed = ed, sd
    start_eff = sd.isoformat()
    end_eff = ed.isoformat()
    with _LOCK:
        data = _read_raw()
        days = data.get("by_day")
        if not isinstance(days, dict):
            return [], start_eff, end_eff
    rows: list[dict[str, Any]] = []
    cur = sd
    while cur <= ed:
        key = cur.isoformat()
        day_row = days.get(key) if isinstance(days, dict) else None
        if isinstance(day_row, dict):
            bot = day_row.get("bot") if isinstance(day_row.get("bot"), dict) else None
            ai = day_row.get("ai") if isinstance(day_row.get("ai"), dict) else None
            if bot or ai:
                rows.append({
                    "date": key,
                    "bot": bot,
                    "ai": ai,
                })
        cur += timedelta(days=1)
    rows.sort(key=itemgetter("date"))
    return rows, start_eff, end_eff
