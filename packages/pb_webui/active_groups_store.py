"""控制台按自然日活跃群集合（收到群消息即计）。"""

from __future__ import annotations

import json
import os
import threading
from contextlib import contextmanager
from datetime import date, timedelta
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from pathlib import Path

_STORE_VER = 1
_MAX_RETAIN_DAYS = 500
_LOCK = threading.RLock()


@contextmanager
def interprocess_stats_lock():
    from pallas.core.foundation.fs_lock import interprocess_file_lock

    with interprocess_file_lock(stats_file_path().with_suffix(".json.lock")):
        yield


def stats_file_path() -> Path:
    from packages.pb_webui.data_dir import pb_webui_data_dir

    return pb_webui_data_dir() / "console_active_groups.json"


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


def _normalize_group_ids(raw: object) -> set[str]:
    out: set[str] = set()
    if isinstance(raw, (set, list, tuple)):
        items = raw
    elif isinstance(raw, dict):
        items = raw.keys()
    else:
        return out
    for item in items:
        key = str(item).strip()
        if not key:
            continue
        try:
            gid = int(key)
        except (TypeError, ValueError):
            continue
        if gid > 0:
            out.add(str(gid))
    return out


def merge_day_groups(existing: object, incoming: object) -> list[str]:
    merged = _normalize_group_ids(existing) | _normalize_group_ids(incoming)
    return sorted(merged, key=lambda s: int(s))


def write_day_groups(day: str, self_id: str, group_ids: object) -> None:
    """写入/合并某日某账号活跃群集合。"""
    write_batch_day_groups([(day, self_id, group_ids)])


def write_batch_day_groups(entries: list[tuple[str, str, object]]) -> None:
    pending: dict[tuple[str, str], set[str]] = {}
    for day, self_id, group_ids in entries:
        sid = str(self_id).strip()
        day_key = str(day).strip()[:10]
        if not sid or len(day_key) < 10:
            continue
        key = (day_key, sid)
        chunk = _normalize_group_ids(group_ids)
        if not chunk and key not in pending:
            pending[key] = set()
            continue
        pending[key] = pending.get(key, set()) | chunk
    if not pending:
        return
    with _LOCK:
        with interprocess_stats_lock():
            data = _read_raw()
            days = data.setdefault("by_day", {})
            if not isinstance(days, dict):
                data["by_day"] = {}
                days = data["by_day"]
            changed = False
            for (day_key, sid), ids in pending.items():
                bots = days.setdefault(day_key, {})
                if not isinstance(bots, dict):
                    days[day_key] = {}
                    bots = days[day_key]
                prev = bots.get(sid)
                merged = merge_day_groups(prev, ids)
                if prev != merged:
                    bots[sid] = merged
                    changed = True
            _trim_old_days(days)
            if changed:
                _atomic_write(data)


def _parse_iso_day(s: str) -> date | None:
    try:
        return date.fromisoformat(str(s).strip()[:10])
    except ValueError:
        return None


def load_day_groups(*, day: str, self_id: str | None = None) -> dict[str, list[str]]:
    """返回 {self_id: [group_id, ...]}。"""
    day_key = str(day).strip()[:10]
    if len(day_key) < 10:
        return {}
    with _LOCK:
        data = _read_raw()
        days = data.get("by_day")
        if not isinstance(days, dict):
            return {}
        bots = days.get(day_key)
        if not isinstance(bots, dict):
            return {}
    out: dict[str, list[str]] = {}
    want = str(self_id).strip() if self_id else None
    for sid, raw in bots.items():
        key = str(sid).strip()
        if not key or (want is not None and key != want):
            continue
        out[key] = merge_day_groups(None, raw)
    return out


def load_daily_active_counts(
    *,
    self_id: str | None,
    start_day: str,
    end_day: str,
) -> list[dict[str, Any]]:
    """按日返回 active_groups 计数行。"""
    sd = _parse_iso_day(start_day)
    ed = _parse_iso_day(end_day)
    if sd is None or ed is None:
        return []
    if sd > ed:
        sd, ed = ed, sd
    with _LOCK:
        data = _read_raw()
        days = data.get("by_day")
        if not isinstance(days, dict):
            return []
        snapshot = {k: v for k, v in days.items() if isinstance(v, dict)}
    rows: list[dict[str, Any]] = []
    want = str(self_id).strip() if self_id else None
    cur = sd
    while cur <= ed:
        key = cur.isoformat()
        bots = snapshot.get(key)
        if isinstance(bots, dict):
            for sid, raw in bots.items():
                sid_s = str(sid).strip()
                if not sid_s or (want is not None and sid_s != want):
                    continue
                ids = _normalize_group_ids(raw)
                rows.append({
                    "date": key,
                    "self_id": sid_s,
                    "active_groups": len(ids),
                })
        cur += timedelta(days=1)
    rows.sort(key=lambda r: (str(r["date"]), str(r["self_id"])))
    return rows


def compute_group_metrics(
    *,
    self_id: str | None,
    today: str,
    mag_days: int = 30,
    live_today: dict[str, set[str]] | None = None,
) -> dict[str, Any]:
    """DAG / MAG / DAG·MAG；live_today 为内存中尚未落盘的当日集合。"""
    today_key = str(today).strip()[:10]
    mag_n = max(1, min(366, int(mag_days)))
    td = _parse_iso_day(today_key)
    if td is None:
        return {
            "dag": 0,
            "mag": 0,
            "dag_mag_ratio": None,
            "mag_days": mag_n,
        }

    want = str(self_id).strip() if self_id else None
    live = live_today or {}

    dag_ids: set[str] = set()
    disk_today = load_day_groups(day=today_key, self_id=want)
    for ids in disk_today.values():
        dag_ids |= set(ids)
    for sid, ids in live.items():
        if want is not None and str(sid).strip() != want:
            continue
        dag_ids |= _normalize_group_ids(ids)

    mag_ids: set[str] = set(dag_ids)
    start = td - timedelta(days=mag_n - 1)
    with _LOCK:
        data = _read_raw()
        days = data.get("by_day")
        snapshot = days if isinstance(days, dict) else {}
    cur = start
    while cur <= td:
        key = cur.isoformat()
        bots = snapshot.get(key)
        if isinstance(bots, dict):
            for sid, raw in bots.items():
                if want is not None and str(sid).strip() != want:
                    continue
                mag_ids |= _normalize_group_ids(raw)
        cur += timedelta(days=1)

    dag = len(dag_ids)
    mag = len(mag_ids)
    ratio = round(dag / mag, 4) if mag > 0 else None
    return {
        "dag": dag,
        "mag": mag,
        "dag_mag_ratio": ratio,
        "mag_days": mag_n,
    }
