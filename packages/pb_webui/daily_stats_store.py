"""控制台按自然日汇总的消息收/发与 Matcher 次数持久化。"""

from __future__ import annotations

import json
import os
import threading
from contextlib import contextmanager
from datetime import date, timedelta
from operator import itemgetter
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Iterable
    from pathlib import Path

_STORE_VER = 1
_MAX_RETAIN_DAYS = 500
_LOCK = threading.RLock()


@contextmanager
def interprocess_stats_lock():
    """跨 hub/worker 进程互斥；分片下仅 hub 写盘，单进程亦可用。"""
    p = stats_file_path().with_suffix(".json.lock")
    p.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(str(p), os.O_CREAT | os.O_RDWR)
    try:
        import fcntl

        fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        try:
            import fcntl

            fcntl.flock(fd, fcntl.LOCK_UN)
        except OSError:
            pass
        os.close(fd)


def merge_day_bot_record(
    existing: dict[str, Any] | None,
    received: int,
    sent: int,
    matcher_runs: int,
    api_calls: int = 0,
) -> dict[str, int]:
    dr = max(0, int(received))
    ds = max(0, int(sent))
    mr = max(0, int(matcher_runs))
    ac = max(0, int(api_calls))
    if isinstance(existing, dict):
        prev_dr = max(0, int(existing.get("received", 0)))
        prev_ds = max(0, int(existing.get("sent", 0)))
        prev_mr = max(0, int(existing.get("matcher_runs", 0)))
        prev_ac = max(0, int(existing.get("api_calls", 0)))
        if dr == ds == mr == ac == 0 and (prev_dr or prev_ds or prev_mr or prev_ac):
            return {
                "received": prev_dr,
                "sent": prev_ds,
                "matcher_runs": prev_mr,
                "api_calls": prev_ac,
            }
        dr = max(dr, prev_dr)
        ds = max(ds, prev_ds)
        mr = max(mr, prev_mr)
        ac = max(ac, prev_ac)
    return {"received": dr, "sent": ds, "matcher_runs": mr, "api_calls": ac}


def stats_file_path() -> Path:
    from packages.pb_webui.data_dir import pb_webui_data_dir

    return pb_webui_data_dir() / "console_daily_stats.json"


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


def write_day_totals(
    day: str,
    self_id: str,
    received: int,
    sent: int,
    matcher_runs: int,
    api_calls: int = 0,
) -> None:
    """写入或覆盖某日某账号的汇总"""
    write_batch_day_totals([(day, self_id, received, sent, matcher_runs, api_calls)])


DayTotalsEntry = tuple[str, str, int, int, int] | tuple[str, str, int, int, int, int]


def write_batch_day_totals(entries: Iterable[DayTotalsEntry]) -> None:
    """批量写入；单次读改写，避免分片多进程交错覆盖 by_day。"""
    pending: dict[tuple[str, str], tuple[int, int, int, int]] = {}
    for entry in entries:
        day, self_id, received, sent, matcher_runs = entry[:5]
        api_calls = int(entry[5]) if len(entry) > 5 else 0
        sid = str(self_id).strip()
        day_key = str(day).strip()[:10]
        if not sid or len(day_key) < 10:
            continue
        key = (day_key, sid)
        dr = max(0, int(received))
        ds = max(0, int(sent))
        mr = max(0, int(matcher_runs))
        ac = max(0, int(api_calls))
        prev = pending.get(key)
        if prev is not None:
            dr = max(dr, prev[0])
            ds = max(ds, prev[1])
            mr = max(mr, prev[2])
            ac = max(ac, prev[3])
        pending[key] = (dr, ds, mr, ac)
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
            for (day_key, sid), (dr, ds, mr, ac) in pending.items():
                bots = days.setdefault(day_key, {})
                if not isinstance(bots, dict):
                    days[day_key] = {}
                    bots = days[day_key]
                prev_rec = bots.get(sid) if isinstance(bots.get(sid), dict) else None
                merged = merge_day_bot_record(prev_rec, dr, ds, mr, ac)
                if prev_rec != merged:
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


def load_range(
    *,
    self_id: str | None,
    start_day: str,
    end_day: str,
) -> tuple[list[dict[str, Any]], str, str]:
    """读取磁盘上 [start_day, end_day] 内每日每账号一行。返回 (rows, start_eff, end_eff)。"""
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
        day_bots = days.get(key) if isinstance(days, dict) else None
        if isinstance(day_bots, dict):
            for bid, rec in day_bots.items():
                if self_id is not None and str(bid) != str(self_id).strip():
                    continue
                if not isinstance(rec, dict):
                    continue
                try:
                    rows.append({
                        "date": key,
                        "self_id": str(bid),
                        "received": max(0, int(rec.get("received", 0))),
                        "sent": max(0, int(rec.get("sent", 0))),
                        "matcher_runs": max(0, int(rec.get("matcher_runs", 0))),
                        "api_calls": max(0, int(rec.get("api_calls", 0))),
                    })
                except (TypeError, ValueError):
                    continue
        cur += timedelta(days=1)
    rows.sort(key=itemgetter("date", "self_id"))
    return rows, start_eff, end_eff


def merge_today_row(
    by_key: dict[tuple[str, str], dict[str, Any]],
    *,
    day: str,
    self_id: str,
    received: int,
    sent: int,
    matcher_runs: int,
    api_calls: int = 0,
) -> None:
    """合并今日一行；live 全 0 时不覆盖磁盘已有非零值。"""
    sid = str(self_id).strip()
    day_key = str(day).strip()[:10]
    if not sid or len(day_key) < 10:
        return
    k = (day_key, sid)
    dr = max(0, int(received))
    ds = max(0, int(sent))
    mr = max(0, int(matcher_runs))
    ac = max(0, int(api_calls))
    if k in by_key:
        prev = by_key[k]
        if dr == ds == mr == ac == 0 and (
            int(prev.get("received", 0))
            or int(prev.get("sent", 0))
            or int(prev.get("matcher_runs", 0))
            or int(prev.get("api_calls", 0))
        ):
            return
        row = by_key[k]
        row["received"] = dr
        row["sent"] = ds
        row["matcher_runs"] = mr
        row["api_calls"] = ac
        return
    by_key[k] = {
        "date": day_key,
        "self_id": sid,
        "received": dr,
        "sent": ds,
        "matcher_runs": mr,
        "api_calls": ac,
    }
