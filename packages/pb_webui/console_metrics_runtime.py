"""Console metrics runtime: state, hooks, flush/sync helpers."""

from __future__ import annotations

import asyncio
import copy
import json
import os
import threading
import time
import traceback
from collections import defaultdict
from operator import itemgetter
from typing import Any

from nonebot import get_bots, logger
from nonebot.adapters import Bot as BaseBot  # noqa: TC002
from nonebot.adapters import Event  # noqa: TC002
from nonebot.matcher import Matcher  # noqa: TC002

from .console_read_cache import drop_read_cache
from .data_dir import pb_webui_data_dir
from .extended_common import shard_hub_console, shard_worker_console

_INIT_LOG_SINK = False

_MSG_STATS: dict[str, dict[str, Any]] = {}  # self_id -> sent/received + 按本地日切片的 day_*
_MSG_TRACKING_INIT = False
# self_id -> 本地自然日；日切时落盘并清零当日计数
_CONSOLE_CAL_DAY: dict[str, str] = {}


def _parse_console_hist_params() -> tuple[int, int]:
    """控制台时序桶参数（默认 1 分钟 × 1440 桶）。

    环境变量：PALLAS_CONSOLE_HIST_BUCKET_SEC、PALLAS_CONSOLE_HIST_MAX_BUCKETS。
    """
    default_bucket, default_max = 60, 1440
    try:
        raw_b = os.environ.get("PALLAS_CONSOLE_HIST_BUCKET_SEC", "").strip()
        bucket_sec = int(raw_b) if raw_b else default_bucket
    except ValueError:
        bucket_sec = default_bucket
    bucket_sec = max(30, min(3600, bucket_sec))

    try:
        raw_m = os.environ.get("PALLAS_CONSOLE_HIST_MAX_BUCKETS", "").strip()
        max_buckets = int(raw_m) if raw_m else default_max
    except ValueError:
        max_buckets = default_max
    max_buckets = max(48, min(10080, max_buckets))

    return bucket_sec, max_buckets


_API_HIST_BUCKET_SEC, _API_HIST_MAX_BUCKETS = _parse_console_hist_params()


def _hist_bucket_start_local(ts: int, bucket_sec: int) -> int:
    """将 Unix 时刻向下取整到 *bucket_sec* 对齐的「本地 wall-clock」桶起点。

    使用进程所在主机的本地时区、以当地自然日 00:00 起算的秒偏移对齐。
    """
    if bucket_sec <= 0:
        return int(ts)
    lt = time.localtime(ts)
    day0 = int(
        time.mktime((
            lt.tm_year,
            lt.tm_mon,
            lt.tm_mday,
            0,
            0,
            0,
            lt.tm_wday,
            lt.tm_yday,
            lt.tm_isdst,
        ))
    )
    offset = int(ts) - day0
    floored = offset - (offset % bucket_sec)
    return day0 + floored


# self_id -> { day_key, by_plugin: { plugin: { runs, errors, day_runs, day_errors, duration_* } } }
_PLUGIN_RUN_STATS: dict[str, dict[str, Any]] = {}
_PLUGIN_RUN_TRACKING_INIT = False
_MATCHER_DURATION_LOG_DIRTY = False
_WORKER_STATS_SYNC_STARTED = False
_UNIFIED_STATS_SYNC_STARTED = False
_REPEATER_HISTORY_SYNC_STARTED = False
_INGRESS_HISTORY_SYNC_STARTED = False
_WORKER_STATS_FAST_FLUSH_SEC = 10.0
_WORKER_STATS_HIST_FLUSH_SEC = 30.0
_WORKER_SHARD_STATS_FAST_FLUSH_SEC = 10.0


def _worker_stats_fast_flush_sec() -> float:
    if shard_worker_console():
        return _WORKER_SHARD_STATS_FAST_FLUSH_SEC
    return _WORKER_STATS_FAST_FLUSH_SEC


# repeater 指标历史按小时落盘；与 repeater_metrics_history._MAX_LINES(24*14) 的 14 天窗口对齐
_REPEATER_HISTORY_FLUSH_SEC = 3600.0
_INGRESS_HISTORY_FLUSH_SEC = 15.0
_EMPTY_MATCHER_HIST_SERIES: dict[str, list[Any]] = {
    "matcher_runs_by_plugin": [],
    "matcher_errors_by_plugin": [],
}
_EMPTY_MATCHER_DUR_HIST_SERIES: dict[str, list[Any]] = {
    "matcher_duration_ms_by_plugin": [],
    "matcher_avg_duration_ms_by_plugin": [],
}


def _is_console_stats_excluded_plugin(plugin: str) -> bool:
    from packages.help.visibility import resolve_console_stats_excluded_plugin_names

    key = str(plugin or "").strip().lower()
    return bool(key) and key in resolve_console_stats_excluded_plugin_names()


# matcher 预处理在 task group 子任务内执行，ContextVar 无法回写到父任务。
_MATCHER_RUN_STARTED_ATTR = "_pallas_matcher_run_started_pc"
_MATCHER_ERROR_LOG_CAP = 80
_MATCHER_DURATION_LOG_CAP = 150
_MATCHER_DURATION_LOG_PER_PLUGIN_CAP = 30
_MATCHER_DURATION_MS_DECIMALS = 3
_MATCHER_ERROR_MSG_MAX = 2000
_MATCHER_ERROR_TB_MAX = 50_000
_MATCHER_ERROR_JSONL_LOCK = threading.Lock()
_MATCHER_DURATION_JSONL_LOCK = threading.Lock()
_LOG_ERROR_LOG_CAP = _MATCHER_ERROR_LOG_CAP
_LOG_ERROR_MSG_MAX = _MATCHER_ERROR_MSG_MAX
_LOG_ERROR_TB_MAX = _MATCHER_ERROR_TB_MAX
_LOG_ERROR_JSONL_LOCK = threading.Lock()
_LOG_ERROR_BUFFER: list[dict[str, Any]] = []


def _ensure_log_sink() -> None:
    global _INIT_LOG_SINK
    from pallas.console.web import install_nonebot_log_sink, set_log_error_capture

    install_nonebot_log_sink()
    set_log_error_capture(_append_log_error_from_sink)
    if _INIT_LOG_SINK:
        return
    _INIT_LOG_SINK = True
    logger.info("[控制台] 日志环已接入 /pallas/api/logs")


def _gpu_metrics() -> dict[str, Any]:
    """GPU 监控：优先 NVML，未安装时返回 unavailable。"""
    fallback = {"available": False, "reason": "pynvml not installed", "devices": []}
    try:
        import pynvml  # type: ignore
    except Exception:  # noqa: BLE001
        return fallback

    try:
        pynvml.nvmlInit()
    except Exception as e:  # noqa: BLE001
        return {"available": False, "reason": str(e), "devices": []}

    devices: list[dict[str, Any]] = []
    try:
        count = int(pynvml.nvmlDeviceGetCount())
        for i in range(count):
            h = pynvml.nvmlDeviceGetHandleByIndex(i)
            mem = pynvml.nvmlDeviceGetMemoryInfo(h)
            util = pynvml.nvmlDeviceGetUtilizationRates(h)
            try:
                temp = int(pynvml.nvmlDeviceGetTemperature(h, pynvml.NVML_TEMPERATURE_GPU))
            except Exception:  # noqa: BLE001
                temp = None
            name_raw = pynvml.nvmlDeviceGetName(h)
            if isinstance(name_raw, (bytes, bytearray)):
                name = name_raw.decode("utf-8", errors="ignore")
            else:
                name = str(name_raw)
            devices.append({
                "index": i,
                "name": name,
                "memory_total": int(getattr(mem, "total", 0) or 0),
                "memory_used": int(getattr(mem, "used", 0) or 0),
                "memory_free": int(getattr(mem, "free", 0) or 0),
                "utilization_gpu": float(getattr(util, "gpu", 0) or 0),
                "utilization_memory": float(getattr(util, "memory", 0) or 0),
                "temperature": temp,
            })
    except Exception as e:  # noqa: BLE001
        return {"available": False, "reason": str(e), "devices": []}
    finally:
        try:
            pynvml.nvmlShutdown()
        except Exception:  # noqa: BLE001
            pass

    return {"available": True, "reason": "", "devices": devices}


def _extract_message_stats(raw: object) -> dict[str, int]:
    """尽量兼容不同 OneBot 实现的 get_status 统计字段。"""
    sent = 0
    recv = 0
    if not isinstance(raw, dict):
        return {"sent": sent, "received": recv}

    _sent_keys = (
        "message_sent",
        "msg_sent",
        "packet_sent",
        "MessageSent",
        "MsgSent",
        "PacketSent",
    )
    _recv_keys = (
        "message_received",
        "msg_received",
        "packet_received",
        "MessageReceived",
        "MsgReceived",
        "PacketReceived",
    )

    stat = raw.get("stat")
    if isinstance(stat, dict):
        for k in _sent_keys:
            v = stat.get(k)
            if isinstance(v, (int, float)):
                sent = max(sent, int(v))
        for k in _recv_keys:
            v = stat.get(k)
            if isinstance(v, (int, float)):
                recv = max(recv, int(v))
    for k in _sent_keys:
        v = raw.get(k)
        if isinstance(v, (int, float)):
            sent = max(sent, int(v))
    for k in _recv_keys:
        v = raw.get(k)
        if isinstance(v, (int, float)):
            recv = max(recv, int(v))
    return {"sent": sent, "received": recv}


def _sum_matcher_day_runs(sid: str) -> int:
    pblock = _PLUGIN_RUN_STATS.get(sid)
    if not isinstance(pblock, dict):
        return 0
    bp = pblock.get("by_plugin")
    if not isinstance(bp, dict):
        return 0
    n = 0
    for prow in bp.values():
        if isinstance(prow, dict):
            n += int(prow.get("day_runs", 0))
    return n


def _console_daily_stats_disk_enabled() -> bool:
    """分片 worker 不写 console_daily_stats.json，由 hub 合并 worker 快照落盘。"""
    return not shard_worker_console()


def _unified_console_live_stats_enabled() -> bool:
    """单进程写 console_live_stats.json 并在启动时恢复。"""

    if shard_worker_console():
        return False
    if shard_hub_console():
        return False
    return True


def _day_totals_from_cluster_bot_blob(rec: dict[str, Any], *, fallback_day: str) -> tuple[str, int, int, int, int]:
    msg = rec.get("msg")
    if not isinstance(msg, dict):
        msg = {}
    day_key = str(rec.get("day_key") or msg.get("day_key") or fallback_day).strip()[:10]
    if len(day_key) < 10:
        day_key = fallback_day
    dr = int(msg.get("day_received", 0)) if isinstance(msg, dict) else 0
    ds = int(msg.get("day_sent", 0)) if isinstance(msg, dict) else 0
    ac = int(msg.get("day_api_total", 0)) if isinstance(msg, dict) else 0
    mr = 0
    bp = rec.get("by_plugin")
    if isinstance(bp, dict):
        for prow in bp.values():
            if isinstance(prow, dict):
                mr += int(prow.get("day_runs", 0))
    return day_key, dr, ds, mr, ac


def _normalize_active_group_ids(raw: object) -> set[str]:
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


def _day_active_groups_from_mem(mem: dict[str, Any] | None) -> set[str]:
    if not isinstance(mem, dict):
        return set()
    return _normalize_active_group_ids(mem.get("day_active_groups"))


def _ensure_day_active_groups(mem: dict[str, Any]) -> set[str]:
    groups = mem.get("day_active_groups")
    if isinstance(groups, set):
        return groups
    normalized = _normalize_active_group_ids(groups)
    mem["day_active_groups"] = normalized
    return normalized


def _record_active_group_from_event(mem: dict[str, Any], event: object) -> None:
    gid = getattr(event, "group_id", None)
    if gid is None:
        return
    try:
        gid_i = int(gid)
    except (TypeError, ValueError):
        return
    if gid_i <= 0:
        return
    _ensure_day_active_groups(mem).add(str(gid_i))


def _collect_active_groups_flush_entries(today: str) -> list[tuple[str, str, set[str]]]:
    """hub/单进程刷盘：合并 worker 与本进程当日活跃群。"""
    bucket: dict[tuple[str, str], set[str]] = {}

    def _merge(day: str, sid: str, ids: set[str]) -> None:
        day_key = str(day).strip()[:10]
        key_sid = str(sid).strip()
        if not key_sid or len(day_key) < 10:
            return
        k = (day_key, key_sid)
        bucket[k] = bucket.get(k, set()) | ids

    if shard_hub_console():
        from pallas.core.platform.shard.console_stats import load_cluster_console_stats_by_sid

        for sid, blob in load_cluster_console_stats_by_sid().items():
            if not isinstance(blob, dict):
                continue
            msg = blob.get("msg") if isinstance(blob.get("msg"), dict) else {}
            day_key = str(blob.get("day_key") or msg.get("day_key") or today).strip()[:10]
            _merge(day_key, str(sid), _normalize_active_group_ids(msg.get("day_active_groups")))

    for sid in set(_MSG_STATS.keys()):
        sid = str(sid).strip()
        if not sid:
            continue
        _rollover_console_day_if_needed(sid, today)
        mem = _MSG_STATS.get(sid)
        _merge(today, sid, _day_active_groups_from_mem(mem if isinstance(mem, dict) else None))

    return [(day, sid, ids) for (day, sid), ids in sorted(bucket.items())]


def _flush_active_groups_disk(today: str) -> None:
    if not _console_daily_stats_disk_enabled():
        return
    from packages.pb_webui import active_groups_store

    entries = _collect_active_groups_flush_entries(today)
    if entries:
        active_groups_store.write_batch_day_groups(entries)


def _merge_console_daily_flush_entry(
    bucket: dict[tuple[str, str], tuple[int, int, int, int]],
    *,
    day: str,
    self_id: str,
    received: int,
    sent: int,
    matcher_runs: int,
    api_calls: int = 0,
) -> None:
    sid = str(self_id).strip()
    day_key = str(day).strip()[:10]
    if not sid or len(day_key) < 10:
        return
    key = (day_key, sid)
    dr = max(0, int(received))
    ds = max(0, int(sent))
    mr = max(0, int(matcher_runs))
    ac = max(0, int(api_calls))
    prev = bucket.get(key)
    if prev is not None:
        dr = max(dr, prev[0])
        ds = max(ds, prev[1])
        mr = max(mr, prev[2])
        ac = max(ac, prev[3])
    bucket[key] = (dr, ds, mr, ac)


def _collect_console_daily_flush_entries(today: str) -> list[tuple[str, str, int, int, int, int]]:
    """hub 定时刷盘：分片下合并各 worker stats 文件 + 本进程内存计数。"""

    bucket: dict[tuple[str, str], tuple[int, int, int, int]] = {}

    if shard_hub_console():
        from pallas.core.platform.shard.console_stats import load_cluster_console_stats_by_sid

        for sid, blob in load_cluster_console_stats_by_sid().items():
            if not isinstance(blob, dict):
                continue
            day_key, dr, ds, mr, ac = _day_totals_from_cluster_bot_blob(blob, fallback_day=today)
            _merge_console_daily_flush_entry(
                bucket,
                day=day_key,
                self_id=str(sid),
                received=dr,
                sent=ds,
                matcher_runs=mr,
                api_calls=ac,
            )

    for sid in set(_MSG_STATS.keys()) | set(_PLUGIN_RUN_STATS.keys()):
        sid = str(sid).strip()
        if not sid:
            continue
        _rollover_console_day_if_needed(sid, today)
        mem = _MSG_STATS.get(sid)
        dr = int(mem.get("day_received", 0)) if isinstance(mem, dict) else 0
        ds = int(mem.get("day_sent", 0)) if isinstance(mem, dict) else 0
        ac = int(mem.get("day_api_total", 0)) if isinstance(mem, dict) else 0
        mr = _sum_matcher_day_runs(sid)
        _merge_console_daily_flush_entry(
            bucket,
            day=today,
            self_id=sid,
            received=dr,
            sent=ds,
            matcher_runs=mr,
            api_calls=ac,
        )

    return [(day, sid, dr, ds, mr, ac) for (day, sid), (dr, ds, mr, ac) in sorted(bucket.items())]


def _rollover_console_day_if_needed(sid: str, today: str) -> None:
    """跨自然日时把上一日的消息收/发与 Matcher 当日计数写入磁盘并清零当日字段。"""
    from packages.pb_webui import daily_stats_store

    sid = str(sid).strip()
    if not sid:
        return
    cur = _CONSOLE_CAL_DAY.get(sid)
    if cur is None:
        _CONSOLE_CAL_DAY[sid] = today
        return
    if cur == today:
        return
    mem = _MSG_STATS.get(sid)
    dr = int(mem.get("day_received", 0)) if isinstance(mem, dict) else 0
    ds = int(mem.get("day_sent", 0)) if isinstance(mem, dict) else 0
    ac = int(mem.get("day_api_total", 0)) if isinstance(mem, dict) else 0
    mr = _sum_matcher_day_runs(sid)
    if _console_daily_stats_disk_enabled():
        daily_stats_store.write_day_totals(cur, sid, dr, ds, mr, ac)
        try:
            from packages.pb_webui import active_groups_store

            active_groups_store.write_day_groups(
                cur,
                sid,
                _day_active_groups_from_mem(mem if isinstance(mem, dict) else None),
            )
        except Exception:  # noqa: BLE001
            pass
    if isinstance(mem, dict):
        mem["day_key"] = today
        mem["day_sent"] = 0
        mem["day_received"] = 0
        mem["day_api_total"] = 0
        mem["day_api_counts"] = {}
        mem["day_active_groups"] = set()
    pblock = _PLUGIN_RUN_STATS.get(sid)
    if isinstance(pblock, dict):
        pblock["day_key"] = today
        log = pblock.get("matcher_duration_log")
        if isinstance(log, list):
            trim_matcher_duration_log_to_local_day(log, today)
        bp = pblock.get("by_plugin")
        if isinstance(bp, dict):
            for prow in bp.values():
                if isinstance(prow, dict):
                    prow["day_runs"] = 0
                    prow["day_errors"] = 0
                    prow["day_duration_ms_sum"] = 0
                    prow["day_duration_count"] = 0
                    prow["day_duration_ms_max"] = 0
    _CONSOLE_CAL_DAY[sid] = today


def _flush_today_console_daily_stats_disk() -> None:
    """定时刷盘：当前自然日内累计值写入磁盘。"""
    try:
        if shard_hub_console():
            from pallas.core.platform.shard.console_stats import prune_stale_worker_stats_bots_sync

            prune_stale_worker_stats_bots_sync()
    except Exception:  # noqa: BLE001
        pass
    if not _console_daily_stats_disk_enabled():
        return
    from packages.pb_webui import daily_stats_store

    today = time.strftime("%Y-%m-%d", time.localtime())
    entries = _collect_console_daily_flush_entries(today)
    if entries:
        daily_stats_store.write_batch_day_totals(entries)
    try:
        _flush_active_groups_disk(today)
    except Exception:  # noqa: BLE001
        pass
    try:
        from pallas.product.llm.task_metrics import flush_stats_sync

        flush_stats_sync()
    except Exception:  # noqa: BLE001
        pass
    try:
        from pallas.product.llm.token_metrics import flush_stats_sync as flush_token_stats_sync

        flush_token_stats_sync()
    except Exception:  # noqa: BLE001
        pass
    try:
        from pallas.product.llm.rag_metrics import flush_rag_stats_sync

        flush_rag_stats_sync()
    except Exception:  # noqa: BLE001
        pass


async def flush_today_console_daily_stats_disk_async() -> None:
    await asyncio.to_thread(_flush_today_console_daily_stats_disk)


def _msg_stats_shard_export(mem: dict[str, Any]) -> dict[str, Any]:
    counts = mem.get("day_api_counts")
    if not isinstance(counts, dict):
        counts = {}
    api_hist = mem.get("api_call_buckets")
    if not isinstance(api_hist, list):
        api_hist = []
    traffic_hist = mem.get("msg_traffic_buckets")
    if not isinstance(traffic_hist, list):
        traffic_hist = []
    day_api: dict[str, int] = {}
    for k, v in counts.items():
        key = str(k).strip()
        if not key:
            continue
        try:
            day_api[key] = int(v)
        except (TypeError, ValueError):
            continue
    return {
        "sent": int(mem.get("sent", 0)),
        "received": int(mem.get("received", 0)),
        "day_sent": int(mem.get("day_sent", 0)),
        "day_received": int(mem.get("day_received", 0)),
        "day_key": str(mem.get("day_key") or ""),
        "day_api_total": int(mem.get("day_api_total", 0)),
        "day_api_counts": day_api,
        "api_call_buckets": [dict(x) for x in api_hist if isinstance(x, dict)],
        "msg_traffic_buckets": [dict(x) for x in traffic_hist if isinstance(x, dict)],
        "day_active_groups": sorted(_day_active_groups_from_mem(mem), key=lambda s: int(s)),
    }


def _msg_stats_shard_import(msg: dict[str, Any], *, today: str) -> dict[str, Any]:
    counts = msg.get("day_api_counts")
    if not isinstance(counts, dict):
        counts = {}
    api_hist = msg.get("api_call_buckets")
    if not isinstance(api_hist, list):
        api_hist = []
    traffic_hist = msg.get("msg_traffic_buckets")
    if not isinstance(traffic_hist, list):
        traffic_hist = []
    day_api: dict[str, int] = {}
    for k, v in counts.items():
        key = str(k).strip()
        if not key:
            continue
        try:
            day_api[key] = int(v)
        except (TypeError, ValueError):
            continue
    return {
        "sent": int(msg.get("sent", 0)),
        "received": int(msg.get("received", 0)),
        "day_sent": int(msg.get("day_sent", 0)),
        "day_received": int(msg.get("day_received", 0)),
        "day_key": str(msg.get("day_key") or today),
        "day_api_total": int(msg.get("day_api_total", 0)),
        "day_api_counts": day_api,
        "api_call_buckets": [dict(x) for x in api_hist if isinstance(x, dict)],
        "msg_traffic_buckets": [dict(x) for x in traffic_hist if isinstance(x, dict)],
        "day_active_groups": _normalize_active_group_ids(msg.get("day_active_groups")),
    }


def _serialize_bot_for_shard_stats(sid: str, *, include_hist: bool = False) -> dict[str, Any]:
    sid = str(sid).strip()
    pblock = _PLUGIN_RUN_STATS.get(sid)
    mem = _MSG_STATS.get(sid)
    by_plugin: dict[str, Any] = {}
    if isinstance(pblock, dict):
        raw_bp = pblock.get("by_plugin")
        if isinstance(raw_bp, dict):
            for pname, prow in raw_bp.items():
                if not isinstance(prow, dict):
                    continue
                by_plugin[str(pname)] = {
                    k: prow[k]
                    for k in (
                        "runs",
                        "errors",
                        "day_runs",
                        "day_errors",
                        "duration_ms_sum",
                        "duration_count",
                        "duration_ms_max",
                        "day_duration_ms_sum",
                        "day_duration_count",
                        "day_duration_ms_max",
                    )
                    if k in prow
                }
    dur_log: list[dict[str, Any]] = []
    if isinstance(pblock, dict):
        raw_log = pblock.get("matcher_duration_log")
        if isinstance(raw_log, list):
            dur_log = [dict(x) for x in raw_log[-_MATCHER_DURATION_LOG_CAP:] if isinstance(x, dict)]
    msg: dict[str, Any] = {}
    if isinstance(mem, dict):
        msg = _msg_stats_shard_export(mem)
    day_key = ""
    if isinstance(pblock, dict):
        day_key = str(pblock.get("day_key") or "")
    if not day_key and isinstance(mem, dict):
        day_key = str(mem.get("day_key") or "")
    out: dict[str, Any] = {
        "day_key": day_key,
        "by_plugin": by_plugin,
        "matcher_duration_log": dur_log,
        "msg": msg,
    }
    if include_hist and isinstance(pblock, dict):
        raw_hist = pblock.get("matcher_hist")
        if isinstance(raw_hist, list):
            out["matcher_hist"] = copy.deepcopy(raw_hist)
    return out


def _collect_worker_console_stats_snapshot(*, include_hist: bool = False) -> dict[str, Any]:
    today = time.strftime("%Y-%m-%d", time.localtime())
    sids = set(_MSG_STATS.keys()) | set(_PLUGIN_RUN_STATS.keys())
    out: dict[str, Any] = {}
    for sid in sids:
        sid = str(sid).strip()
        if not sid:
            continue
        _rollover_console_day_if_needed(sid, today)
        out[sid] = _serialize_bot_for_shard_stats(sid, include_hist=include_hist)
    return out


def flush_unified_console_live_stats_sync(*, include_hist: bool = False) -> None:
    if not _unified_console_live_stats_enabled():
        return
    from packages.pb_webui import console_live_stats

    console_live_stats.write_bots_sync(
        _collect_worker_console_stats_snapshot(include_hist=include_hist),
        preserve_matcher_hist=not include_hist,
    )
    _flush_matcher_duration_log_if_dirty()


async def flush_unified_console_live_stats_async(*, include_hist: bool = False) -> None:
    await asyncio.to_thread(flush_unified_console_live_stats_sync, include_hist=include_hist)


def flush_worker_shard_console_stats_sync(*, include_hist: bool = False) -> None:
    from packages.repeater.runtime_stats import repeater_runtime_cache_snapshot
    from pallas.core.platform.ingress.dispatch_metrics import (
        dispatch_metrics_snapshot as ingress_dispatch_metrics_snapshot,
    )
    from pallas.core.platform.shard.console_stats import (
        filter_bots_for_authoritative_shard,
        process_memory_snapshot,
        write_worker_stats_sync,
    )
    from pallas.core.platform.shard.coord_pending import coord_pending_snapshot_sync
    from pallas.core.platform.shard.ingress_metrics import ingress_metrics_snapshot
    from pallas.core.platform.shard.presence import (
        filter_local_qq_ids_for_presence,
        reconcile_local_worker_presence_sync,
    )
    from pallas.core.platform.shard.registry.config import get_shard_registry_settings
    from pallas.core.platform.shard.repeater_ingress_metrics import repeater_ingress_metrics_snapshot
    from pallas.product.llm.memory_rag_metrics import llm_memory_rag_metrics_snapshot
    from pallas.product.llm.provider_request_metrics import llm_provider_request_metrics_snapshot
    from pallas.product.llm.rag_metrics import llm_rag_metrics_snapshot
    from pallas.product.llm.task_metrics import llm_task_metrics_snapshot
    from pallas.product.llm.token_metrics import llm_token_metrics_snapshot

    def _worker_draw_stats_snapshot() -> dict:
        try:
            from pallas_plugin_draw.draw_stats_store import draw_stats_snapshot

            return draw_stats_snapshot(include_persisted=True)
        except Exception:
            return {}

    if not shard_worker_console():
        return
    shard_id = int(get_shard_registry_settings().shard_id)
    local_qq: set[int] = set()
    try:
        from nonebot import get_bots

        local_qq = {int(k) for k in get_bots().keys() if str(k).isdigit()}
        local_qq = filter_local_qq_ids_for_presence(local_qq)
        reconcile_local_worker_presence_sync(shard_id=shard_id, local_qq_ids=local_qq)
    except Exception:
        pass
    snapshot = _collect_worker_console_stats_snapshot(include_hist=include_hist)
    snapshot = filter_bots_for_authoritative_shard(shard_id, snapshot, local_qq_ids=local_qq)
    write_worker_stats_sync(
        shard_id=shard_id,
        bots=snapshot,
        preserve_matcher_hist=not include_hist,
        worker_meta={
            "ingress": ingress_metrics_snapshot(),
            "ingress_dispatch": ingress_dispatch_metrics_snapshot(),
            "repeater_ingress": repeater_ingress_metrics_snapshot(),
            "repeater_cache": repeater_runtime_cache_snapshot(),
            "coord_pending": coord_pending_snapshot_sync(),
            "process_memory": process_memory_snapshot(),
            "llm_task": llm_task_metrics_snapshot(),
            "llm_token": llm_token_metrics_snapshot(include_persisted=True),
            "llm_provider_request": llm_provider_request_metrics_snapshot(include_persisted=True),
            "llm_rag": llm_rag_metrics_snapshot(include_persisted=True),
            "llm_memory_rag": llm_memory_rag_metrics_snapshot(include_persisted=True),
            "llm_draw": _worker_draw_stats_snapshot(),
        },
    )


async def flush_worker_shard_console_stats_async(*, include_hist: bool = False) -> None:
    # QQ 健康探测较重，只挂在慢刷（hist）路径，避免每 3s 打 get_status。
    if include_hist:
        try:
            from pallas.core.platform.shard.presence_health import apply_presence_qq_health_probes

            await apply_presence_qq_health_probes()
        except Exception:
            pass
    await asyncio.to_thread(flush_worker_shard_console_stats_sync, include_hist=include_hist)


def flush_repeater_metrics_history_sync() -> bool:
    """单点写 repeater 指标历史：仅 hub / 单进程执行，写真实集群聚合而非单 worker 快照。

    分片下各 worker 不再各自追加（会刷爆 14 天保留窗口），改由 hub 用
    aggregate_shard_observability() 的跨 worker 聚合按小时落一行。
    """
    if shard_worker_console():
        return False
    from pallas.core.platform.shard.observability import aggregate_shard_observability
    from pallas.core.platform.shard.repeater_ingress_metrics import repeater_ingress_metrics_snapshot

    from .repeater_metrics_history import append_repeater_metrics_history

    obs = aggregate_shard_observability()
    cluster = obs.get("repeater_ingress_cluster")
    if not isinstance(cluster, dict) or not cluster:
        return False
    return append_repeater_metrics_history(
        cluster=cluster,
        process=repeater_ingress_metrics_snapshot(),
        sharded=bool(obs.get("sharded")),
    )


async def flush_repeater_metrics_history_async() -> bool:
    return await asyncio.to_thread(flush_repeater_metrics_history_sync)


def flush_ingress_metrics_history_sync() -> bool:
    """仅 hub / 单进程追加集群入站采样，避免分片 worker 重复写盘。"""
    if shard_worker_console():
        return False
    from pallas.core.platform.shard.dispatch_observability import aggregate_ingress_dispatch

    from .ingress_metrics_history import append_ingress_metrics_history

    return append_ingress_metrics_history(snapshot=aggregate_ingress_dispatch())


async def flush_ingress_metrics_history_async() -> bool:
    return await asyncio.to_thread(flush_ingress_metrics_history_sync)


def _apply_console_stats_boot_snapshot(bots: dict[str, dict[str, Any]]) -> bool:
    if not bots:
        return False
    today = time.strftime("%Y-%m-%d", time.localtime())
    for sid, rec in bots.items():
        if not isinstance(rec, dict):
            continue
        sid = str(sid).strip()
        if not sid:
            continue
        bp = rec.get("by_plugin")
        bucket = _PLUGIN_RUN_STATS.setdefault(
            sid,
            {"day_key": str(rec.get("day_key") or today), "by_plugin": {}, "matcher_hist": []},
        )
        if isinstance(bp, dict):
            bucket["by_plugin"] = copy.deepcopy(bp)
        bucket["day_key"] = str(rec.get("day_key") or today)
        hist = rec.get("matcher_hist")
        if isinstance(hist, list):
            bucket["matcher_hist"] = copy.deepcopy(hist)
        log = rec.get("matcher_duration_log")
        if isinstance(log, list):
            bucket["matcher_duration_log"] = [dict(x) for x in log[-_MATCHER_DURATION_LOG_CAP:] if isinstance(x, dict)]
        msg = rec.get("msg")
        if isinstance(msg, dict):
            _MSG_STATS[sid] = _msg_stats_shard_import(msg, today=today)
        _CONSOLE_CAL_DAY[sid] = str(bucket.get("day_key") or today)
    return True


def _restore_worker_console_stats_from_shard_file() -> None:
    from pallas.core.platform.shard.console_stats import load_worker_console_stats_for_boot
    from pallas.core.platform.shard.registry.config import get_shard_registry_settings

    if not shard_worker_console():
        return
    shard_id = int(get_shard_registry_settings().shard_id)
    _apply_console_stats_boot_snapshot(load_worker_console_stats_for_boot(shard_id))


def _restore_unified_console_stats_from_daily_disk_fallback() -> bool:
    """无 live 快照时，从已刷盘的按日汇总恢复当日收/发。"""
    from packages.pb_webui import daily_stats_store

    today = time.strftime("%Y-%m-%d", time.localtime())
    rows, _, _ = daily_stats_store.load_range(
        self_id=None,
        start_day=today,
        end_day=today,
    )
    if not rows:
        return False
    for row in rows:
        sid = str(row.get("self_id") or "").strip()
        if not sid:
            continue
        dr = max(0, int(row.get("received", 0)))
        ds = max(0, int(row.get("sent", 0)))
        if dr == 0 and ds == 0:
            continue
        mem = _MSG_STATS.setdefault(
            sid,
            {
                "sent": 0,
                "received": 0,
                "day_sent": 0,
                "day_received": 0,
                "day_key": today,
                "day_api_total": 0,
                "day_api_counts": {},
                "api_call_buckets": [],
                "msg_traffic_buckets": [],
            },
        )
        mem["day_key"] = today
        mem["day_received"] = max(int(mem.get("day_received", 0)), dr)
        mem["day_sent"] = max(int(mem.get("day_sent", 0)), ds)
        _CONSOLE_CAL_DAY[sid] = today
    return True


def _restore_unified_console_stats_from_live_file() -> bool:
    if not _unified_console_live_stats_enabled():
        return False
    from packages.pb_webui import console_live_stats

    if _apply_console_stats_boot_snapshot(console_live_stats.read_bots_for_boot()):
        return True
    return _restore_unified_console_stats_from_daily_disk_fallback()


def start_worker_shard_console_stats_sync() -> None:
    global _WORKER_STATS_SYNC_STARTED
    if _WORKER_STATS_SYNC_STARTED:
        return

    if not shard_worker_console():
        return
    _WORKER_STATS_SYNC_STARTED = True

    async def _fast_loop() -> None:
        while True:
            try:
                await flush_worker_shard_console_stats_async(include_hist=False)
                await flush_today_console_daily_stats_disk_async()
            except Exception:  # noqa: BLE001
                pass
            await asyncio.sleep(_worker_stats_fast_flush_sec())

    async def _hist_loop() -> None:
        while True:
            try:
                await flush_worker_shard_console_stats_async(include_hist=True)
            except Exception:  # noqa: BLE001
                pass
            await asyncio.sleep(_WORKER_STATS_HIST_FLUSH_SEC)

    asyncio.create_task(_fast_loop())
    asyncio.create_task(_hist_loop())


def start_unified_console_stats_sync() -> None:
    global _UNIFIED_STATS_SYNC_STARTED
    if _UNIFIED_STATS_SYNC_STARTED:
        return
    if not _unified_console_live_stats_enabled():
        return
    _UNIFIED_STATS_SYNC_STARTED = True

    async def _fast_loop() -> None:
        while True:
            try:
                await flush_unified_console_live_stats_async(include_hist=False)
                await flush_today_console_daily_stats_disk_async()
            except Exception:  # noqa: BLE001
                pass
            await asyncio.sleep(_worker_stats_fast_flush_sec())

    async def _hist_loop() -> None:
        while True:
            try:
                await flush_unified_console_live_stats_async(include_hist=True)
            except Exception:  # noqa: BLE001
                pass
            await asyncio.sleep(_WORKER_STATS_HIST_FLUSH_SEC)

    asyncio.create_task(_fast_loop())
    asyncio.create_task(_hist_loop())


def start_repeater_metrics_history_sync() -> None:
    """hub / 单进程按小时落 repeater 指标历史；分片 worker 不参与（由 hub 聚合）。"""
    global _REPEATER_HISTORY_SYNC_STARTED
    if _REPEATER_HISTORY_SYNC_STARTED:
        return
    if shard_worker_console():
        return
    _REPEATER_HISTORY_SYNC_STARTED = True

    async def _loop() -> None:
        while True:
            try:
                await flush_repeater_metrics_history_async()
            except Exception:  # noqa: BLE001
                pass
            await asyncio.sleep(_REPEATER_HISTORY_FLUSH_SEC)

    asyncio.create_task(_loop())


def start_ingress_metrics_history_sync() -> None:
    global _INGRESS_HISTORY_SYNC_STARTED
    if _INGRESS_HISTORY_SYNC_STARTED or shard_worker_console():
        return
    _INGRESS_HISTORY_SYNC_STARTED = True

    async def _loop() -> None:
        while True:
            try:
                await flush_ingress_metrics_history_async()
            except Exception:  # noqa: BLE001
                pass
            await asyncio.sleep(_INGRESS_HISTORY_FLUSH_SEC)

    asyncio.create_task(_loop())


def ensure_console_metrics_hooks() -> None:
    """单进程 / hub WebUI 与分片 worker共用。"""
    from .system_home_api import _ensure_bot_session_hooks

    _ensure_bot_session_hooks()
    _init_message_tracking()
    _init_plugin_run_tracking()
    start_unified_console_stats_sync()
    start_repeater_metrics_history_sync()
    start_ingress_metrics_history_sync()


def _msg_stats_get_mut(sid: str) -> dict[str, Any]:
    """返回可写的内存统计行；跨本地自然日时清零当日计数。"""
    today = time.strftime("%Y-%m-%d", time.localtime())
    _rollover_console_day_if_needed(sid, today)
    rec = _MSG_STATS.setdefault(
        sid,
        {
            "sent": 0,
            "received": 0,
            "day_sent": 0,
            "day_received": 0,
            "day_key": today,
            "day_api_total": 0,
            "day_api_counts": {},
            "api_call_buckets": [],
            "msg_traffic_buckets": [],
            "day_active_groups": set(),
        },
    )
    rec["day_key"] = today
    rec.setdefault("sent", 0)
    rec.setdefault("received", 0)
    rec.setdefault("day_sent", 0)
    rec.setdefault("day_received", 0)
    rec.setdefault("day_api_total", 0)
    if not isinstance(rec.get("day_api_counts"), dict):
        rec["day_api_counts"] = {}
    if not isinstance(rec.get("api_call_buckets"), list):
        rec["api_call_buckets"] = []
    if not isinstance(rec.get("msg_traffic_buckets"), list):
        rec["msg_traffic_buckets"] = []
    _ensure_day_active_groups(rec)
    return rec


_HIST_API_SERIES_MAX = 24
_HIST_PLUGIN_SERIES_MAX = 20


def _api_call_history_bump(row: dict[str, Any], api: str) -> None:
    """按时间桶记录各接口成功调用次数。"""
    api_key = str(api).strip() or "_"
    now = int(time.time())
    bucket = _hist_bucket_start_local(now, _API_HIST_BUCKET_SEC)
    cutoff = bucket - (_API_HIST_MAX_BUCKETS - 1) * _API_HIST_BUCKET_SEC
    hist = row.setdefault("api_call_buckets", [])
    if not isinstance(hist, list):
        row["api_call_buckets"] = []
        hist = row["api_call_buckets"]
    i = 0
    while i < len(hist):
        h = hist[i]
        if not isinstance(h, dict):
            hist.pop(i)
            continue
        try:
            at = int(h.get("at") or 0)
        except (TypeError, ValueError):
            hist.pop(i)
            continue
        if at < cutoff:
            hist.pop(i)
        else:
            i += 1
    if hist and isinstance(hist[-1], dict):
        try:
            last_at = int(hist[-1].get("at") or 0)
        except (TypeError, ValueError):
            last_at = 0
        if last_at == bucket:
            apis = hist[-1].setdefault("apis", {})
            if not isinstance(apis, dict):
                hist[-1]["apis"] = {}
                apis = hist[-1]["apis"]
            apis[api_key] = int(apis.get(api_key, 0)) + 1
            return
    hist.append({"at": bucket, "apis": {api_key: 1}})


def _msg_traffic_history_bump(row: dict[str, Any], *, recv_delta: int = 0, sent_delta: int = 0) -> None:
    """按与协议 API 相同的时间桶记录消息收/发条数。"""
    try:
        rd = int(recv_delta)
        sd = int(sent_delta)
    except (TypeError, ValueError):
        return
    if rd <= 0 and sd <= 0:
        return
    now = int(time.time())
    bucket = _hist_bucket_start_local(now, _API_HIST_BUCKET_SEC)
    cutoff = bucket - (_API_HIST_MAX_BUCKETS - 1) * _API_HIST_BUCKET_SEC
    hist = row.setdefault("msg_traffic_buckets", [])
    if not isinstance(hist, list):
        row["msg_traffic_buckets"] = []
        hist = row["msg_traffic_buckets"]
    i = 0
    while i < len(hist):
        h = hist[i]
        if not isinstance(h, dict):
            hist.pop(i)
            continue
        try:
            at = int(h.get("at") or 0)
        except (TypeError, ValueError):
            hist.pop(i)
            continue
        if at < cutoff:
            hist.pop(i)
        else:
            i += 1
    if hist and isinstance(hist[-1], dict):
        try:
            last_at = int(hist[-1].get("at") or 0)
        except (TypeError, ValueError):
            last_at = 0
        if last_at == bucket:
            if rd > 0:
                hist[-1]["received"] = int(hist[-1].get("received", 0)) + rd
            if sd > 0:
                hist[-1]["sent"] = int(hist[-1].get("sent", 0)) + sd
            return
    entry: dict[str, Any] = {"at": bucket}
    if rd > 0:
        entry["received"] = rd
    if sd > 0:
        entry["sent"] = sd
    hist.append(entry)


def _msg_traffic_history_public(row: dict[str, Any]) -> list[dict[str, Any]]:
    raw = row.get("msg_traffic_buckets")
    if not isinstance(raw, list) or not raw:
        return []
    out: list[dict[str, Any]] = []
    for it in raw:
        if not isinstance(it, dict) or "at" not in it:
            continue
        try:
            at = int(it["at"])
        except (TypeError, ValueError):
            continue
        try:
            nr = int(it.get("received", 0))
        except (TypeError, ValueError):
            nr = 0
        try:
            ns = int(it.get("sent", 0))
        except (TypeError, ValueError):
            ns = 0
        out.append({"at": at, "received": nr, "sent": ns})
    out.sort(key=lambda x: int(x["at"]))
    return out


def _legacy_api_hist_aggregate(row: dict[str, Any]) -> list[dict[str, Any]]:
    raw = row.get("api_hist")
    if not isinstance(raw, list):
        return []
    out: list[dict[str, Any]] = []
    for it in raw:
        if not isinstance(it, dict) or "at" not in it:
            continue
        try:
            out.append({"at": int(it["at"]), "total": int(it.get("total", 0))})
        except (TypeError, ValueError):
            continue
    out.sort(key=lambda x: int(x["at"]))
    return out


def _api_call_history_aggregate(row: dict[str, Any]) -> list[dict[str, Any]]:
    raw = row.get("api_call_buckets")
    if not isinstance(raw, list) or not raw:
        return _legacy_api_hist_aggregate(row)
    out: list[dict[str, Any]] = []
    for it in raw:
        if not isinstance(it, dict) or "at" not in it:
            continue
        apis = it.get("apis")
        tot = 0
        if isinstance(apis, dict):
            for v in apis.values():
                try:
                    tot += int(v)
                except (TypeError, ValueError):
                    pass
        try:
            out.append({"at": int(it["at"]), "total": tot})
        except (TypeError, ValueError):
            continue
    out.sort(key=lambda x: int(x["at"]))
    return out


def _ranked_api_names_for_series(row: dict[str, Any], *, limit: int) -> list[str]:
    counts = row.get("day_api_counts")
    ranked: list[str] = []
    if isinstance(counts, dict) and counts:
        ranked = sorted(counts.keys(), key=lambda k: -int(counts.get(k, 0) or 0))
        ranked = [str(k) for k in ranked if str(k).strip()][:limit]
        return ranked
    acc: dict[str, int] = {}
    raw = row.get("api_call_buckets")
    if isinstance(raw, list):
        for it in raw:
            apis = it.get("apis") if isinstance(it, dict) else None
            if not isinstance(apis, dict):
                continue
            for k, v in apis.items():
                try:
                    acc[str(k)] = acc.get(str(k), 0) + int(v)
                except (TypeError, ValueError):
                    continue
    ranked = sorted(acc.keys(), key=lambda k: -acc[k])[:limit]
    return ranked


def _api_call_history_by_api_series(row: dict[str, Any], *, limit: int = _HIST_API_SERIES_MAX) -> list[dict[str, Any]]:
    raw = row.get("api_call_buckets")
    if not isinstance(raw, list) or not raw:
        return []
    names = _ranked_api_names_for_series(row, limit=limit)
    if not names:
        return []
    buckets = sorted(
        [x for x in raw if isinstance(x, dict) and "at" in x],
        key=lambda x: int(x.get("at") or 0),
    )
    out: list[dict[str, Any]] = []
    for an in names:
        points: list[dict[str, Any]] = []
        for it in buckets:
            apis = it.get("apis")
            n = 0
            if isinstance(apis, dict):
                try:
                    n = int(apis.get(an, 0))
                except (TypeError, ValueError):
                    n = 0
            try:
                points.append({"at": int(it["at"]), "total": n})
            except (TypeError, ValueError):
                continue
        out.append({"api": str(an), "points": points})
    return out


def _api_call_history_public(row: dict[str, Any]) -> list[dict[str, Any]]:
    """兼容旧字段名：聚合曲线。"""
    return _api_call_history_aggregate(row)


def _top_api_call_today(counts: object) -> tuple[str, int]:
    if not isinstance(counts, dict) or not counts:
        return "", 0
    top_n = 0
    top_name = ""
    for name, c in counts.items():
        try:
            n = int(c)
        except (TypeError, ValueError):
            continue
        if n > top_n:
            top_n = n
            top_name = str(name)
    return top_name, top_n


def _init_message_tracking() -> None:
    """注册消息钩子：收/发计数与时间桶。"""
    global _MSG_TRACKING_INIT
    if _MSG_TRACKING_INIT:
        return
    _MSG_TRACKING_INIT = True

    from nonebot.adapters import Bot as BaseBot
    from nonebot.message import event_preprocessor

    _send_apis = frozenset({"send_msg", "send_group_msg", "send_private_msg", "send_message"})
    _api_count_exclude = _send_apis | frozenset(
        {
            "get_status",
            "get_login_info",
            "get_version",
            "can_send_image",
            "can_send_record",
            "get_cookies",
            "get_csrf_token",
            "get_msg",
        },
    )

    @BaseBot.on_called_api
    async def _count_sent(
        bot: BaseBot,
        exception: Exception | None,
        api: str,
        data: dict[str, Any],
        result: Any,
    ) -> None:
        if exception is None and api in _send_apis:
            sid = str(getattr(bot, "self_id", "") or "").strip()
            if sid:
                row = _msg_stats_get_mut(sid)
                row["sent"] = int(row["sent"]) + 1
                row["day_sent"] = int(row["day_sent"]) + 1
                _msg_traffic_history_bump(row, sent_delta=1)

    @BaseBot.on_called_api
    async def _count_protocol_api_calls(
        bot: BaseBot,
        exception: Exception | None,
        api: str,
        data: dict[str, Any],
        result: Any,
    ) -> None:
        if exception is not None:
            return
        if not api or api in _api_count_exclude or str(api).startswith("_"):
            return
        sid = str(getattr(bot, "self_id", "") or "").strip()
        if not sid:
            return
        row = _msg_stats_get_mut(sid)
        counts = row.get("day_api_counts")
        if not isinstance(counts, dict):
            counts = {}
            row["day_api_counts"] = counts
        row["day_api_total"] = int(row.get("day_api_total", 0)) + 1
        counts[str(api)] = int(counts.get(str(api), 0)) + 1
        _api_call_history_bump(row, str(api))

    @event_preprocessor
    async def _count_received(bot: BaseBot, event: Event) -> None:
        try:
            if event.get_type() == "message":
                sid = str(getattr(bot, "self_id", "") or "").strip()
                if sid:
                    row = _msg_stats_get_mut(sid)
                    row["received"] = int(row["received"]) + 1
                    row["day_received"] = int(row["day_received"]) + 1
                    _msg_traffic_history_bump(row, recv_delta=1)
                    _record_active_group_from_event(row, event)
        except Exception:  # noqa: BLE001
            pass


def _message_stats_row_from_mem(
    *,
    sid: str,
    connection_key: str,
    mem: dict[str, Any],
) -> dict[str, Any]:
    counts = mem.get("day_api_counts")
    top_name, top_cnt = _top_api_call_today(counts)
    return {
        "self_id": sid,
        "connection_key": connection_key,
        "sent": int(mem.get("sent", 0)),
        "received": int(mem.get("received", 0)),
        "today_sent": int(mem.get("day_sent", 0)),
        "today_received": int(mem.get("day_received", 0)),
        "today_api_calls": int(mem.get("day_api_total", 0)),
        "today_active_groups": len(_day_active_groups_from_mem(mem)),
        "today_top_api": top_name,
        "today_top_api_count": top_cnt,
        "api_calls_history": _api_call_history_public(mem),
        "api_calls_history_by_api": _api_call_history_by_api_series(mem),
        "message_traffic_history": _msg_traffic_history_public(mem),
    }


def _message_stats_mem_from_shard_blob(rec: dict[str, Any]) -> dict[str, Any]:
    msg = rec.get("msg")
    if not isinstance(msg, dict):
        msg = {}
    return _msg_stats_shard_import(msg, today=str(msg.get("day_key") or ""))


async def _message_stats_overview(*, self_id: str | None) -> dict[str, Any]:
    from .social_api import _is_onebot_v11_bot

    rows: list[dict[str, Any]] = []
    total_sent = 0
    total_received = 0
    total_today_sent = 0
    total_today_received = 0
    want = str(self_id).strip() if self_id else None

    def _accum(row: dict[str, Any]) -> None:
        nonlocal total_sent, total_received, total_today_sent, total_today_received
        rows.append(row)
        total_sent += int(row["sent"])
        total_received += int(row["received"])
        total_today_sent += int(row["today_sent"])
        total_today_received += int(row["today_received"])

    if shard_hub_console():
        from pallas.core.platform.shard.console_stats import load_cluster_console_stats_by_sid
        from pallas.core.platform.shard.presence import read_presence_bots

        cluster = load_cluster_console_stats_by_sid()
        seen: set[str] = set()

        def _sort_key(s: str) -> tuple[int, str]:
            return (int(s), s) if s.isdigit() else (10**18, s)

        for sid in sorted(read_presence_bots().keys(), key=_sort_key):
            if want and sid != want:
                continue
            rec = read_presence_bots()[sid]
            blob = cluster.get(sid, {})
            mem = _message_stats_mem_from_shard_blob(blob if isinstance(blob, dict) else {})
            _accum(
                _message_stats_row_from_mem(
                    sid=sid,
                    connection_key=str(rec.get("connection_key") or sid),
                    mem=mem,
                )
            )
            seen.add(sid)
        for key, bot in get_bots().items():
            sid = str(getattr(bot, "self_id", "") or "").strip()
            if not sid or sid in seen:
                continue
            if want and sid != want:
                continue
            if not _is_onebot_v11_bot(bot):
                continue
            mem = _msg_stats_get_mut(sid)
            sent = int(mem["sent"])
            received = int(mem["received"])
            try:
                status_raw = await bot.call_api("get_status")  # type: ignore[union-attr]
                api_stats = _extract_message_stats(status_raw)
                sent = max(sent, api_stats["sent"])
                received = max(received, api_stats["received"])
            except Exception:  # noqa: BLE001
                pass
            mem = dict(mem)
            mem["sent"] = sent
            mem["received"] = received
            _accum(_message_stats_row_from_mem(sid=sid, connection_key=str(key), mem=mem))
            seen.add(sid)
    else:
        for key, bot in get_bots().items():
            sid = str(getattr(bot, "self_id", "") or "").strip()
            if not sid:
                continue
            if want and sid != want:
                continue
            if not _is_onebot_v11_bot(bot):
                continue
            mem = _msg_stats_get_mut(sid)
            sent = int(mem["sent"])
            received = int(mem["received"])
            try:
                status_raw = await bot.call_api("get_status")  # type: ignore[union-attr]
                api_stats = _extract_message_stats(status_raw)
                sent = max(sent, api_stats["sent"])
                received = max(received, api_stats["received"])
            except Exception:  # noqa: BLE001
                pass
            mem = dict(mem)
            mem["sent"] = sent
            mem["received"] = received
            _accum(_message_stats_row_from_mem(sid=sid, connection_key=str(key), mem=mem))
    return {
        "total_sent": total_sent,
        "total_received": total_received,
        "today_sent": total_today_sent,
        "today_received": total_today_received,
        "api_calls_history_bucket_sec": _API_HIST_BUCKET_SEC,
        "api_calls_history_max_buckets": _API_HIST_MAX_BUCKETS,
        "message_traffic_history_bucket_sec": _API_HIST_BUCKET_SEC,
        "message_traffic_history_max_buckets": _API_HIST_MAX_BUCKETS,
        "bots": rows,
    }


def _plugin_short_name_from_matcher(matcher: object) -> str:
    module_name = getattr(matcher, "plugin_name", None)
    if module_name:
        parts = str(module_name).split(".")
        for part in reversed(parts):
            if part != "__init__":
                return part
    return str(module_name or "") or "unknown"


def _plugin_run_bot_bucket(sid: str) -> dict[str, Any]:
    today = time.strftime("%Y-%m-%d", time.localtime())
    _rollover_console_day_if_needed(sid, today)
    rec = _PLUGIN_RUN_STATS.setdefault(sid, {"day_key": today, "by_plugin": {}, "matcher_hist": []})
    rec.setdefault("by_plugin", {})
    rec["day_key"] = today
    if not isinstance(rec.get("matcher_hist"), list):
        rec["matcher_hist"] = []
    return rec


def _plugin_run_plugin_row(sid: str, plugin: str) -> dict[str, Any]:
    rec = _plugin_run_bot_bucket(sid)
    by_plugin = rec["by_plugin"]
    row = by_plugin.setdefault(
        plugin,
        {
            "runs": 0,
            "errors": 0,
            "day_runs": 0,
            "day_errors": 0,
            "duration_ms_sum": 0,
            "duration_count": 0,
            "duration_ms_max": 0,
            "day_duration_ms_sum": 0,
            "day_duration_count": 0,
            "day_duration_ms_max": 0,
        },
    )
    row.setdefault("runs", 0)
    row.setdefault("errors", 0)
    row.setdefault("day_runs", 0)
    row.setdefault("day_errors", 0)
    row.setdefault("duration_ms_sum", 0)
    row.setdefault("duration_count", 0)
    row.setdefault("duration_ms_max", 0)
    row.setdefault("day_duration_ms_sum", 0)
    row.setdefault("day_duration_count", 0)
    row.setdefault("day_duration_ms_max", 0)
    return row


def _round_duration_ms(value: float) -> float:
    return max(0.0, round(float(value), _MATCHER_DURATION_MS_DECIMALS))


def _avg_duration_ms(ms_sum: int | float, count: int) -> float | None:
    if count <= 0:
        return None
    return _round_duration_ms(float(ms_sum) / int(count))


def _duration_ms_float(value: object) -> float:
    try:
        return _round_duration_ms(float(value or 0))
    except (TypeError, ValueError):
        return 0.0


def mark_matcher_run_started(matcher: object) -> None:
    setattr(matcher, _MATCHER_RUN_STARTED_ATTR, time.perf_counter())


def take_matcher_run_started(matcher: object) -> float | None:
    started = getattr(matcher, _MATCHER_RUN_STARTED_ATTR, None)
    if hasattr(matcher, _MATCHER_RUN_STARTED_ATTR):
        delattr(matcher, _MATCHER_RUN_STARTED_ATTR)
    if isinstance(started, (int, float)):
        return float(started)
    return None


def _matcher_elapsed_ms(started: float | None) -> float:
    """Matcher 墙钟耗时。"""
    if started is None:
        return 0.0
    return _round_duration_ms((time.perf_counter() - started) * 1000)


def _record_plugin_run_duration(sid: str, plugin: str, elapsed_ms: int | float) -> None:
    ms = _duration_ms_float(elapsed_ms)
    row = _plugin_run_plugin_row(sid, plugin)
    row["duration_ms_sum"] = _round_duration_ms(_duration_ms_float(row["duration_ms_sum"]) + ms)
    row["duration_count"] = int(row["duration_count"]) + 1
    row["duration_ms_max"] = max(_duration_ms_float(row["duration_ms_max"]), ms)
    row["day_duration_ms_sum"] = _round_duration_ms(_duration_ms_float(row["day_duration_ms_sum"]) + ms)
    row["day_duration_count"] = int(row["day_duration_count"]) + 1
    row["day_duration_ms_max"] = max(_duration_ms_float(row["day_duration_ms_max"]), ms)


def _append_matcher_error_log(sid: str, plugin: str, exception: BaseException) -> None:
    """进程内环形缓冲 + jsonl；与定时清理共用锁，避免与每日清空交错。"""

    tb = "".join(
        traceback.format_exception(
            type(exception),
            exception,
            exception.__traceback__,
        )
    )
    if len(tb) > _MATCHER_ERROR_TB_MAX:
        tb = tb[:_MATCHER_ERROR_TB_MAX] + "\n…(truncated)"
    msg = str(exception)
    if len(msg) > _MATCHER_ERROR_MSG_MAX:
        msg = msg[:_MATCHER_ERROR_MSG_MAX] + "…"
    entry: dict[str, Any] = {
        "at": int(time.time()),
        "plugin": plugin,
        "exc_type": type(exception).__name__,
        "message": msg,
        "traceback": tb,
    }
    line_obj = {**entry, "self_id": sid}
    try:
        path = pb_webui_data_dir() / "matcher_errors.jsonl"
        line = json.dumps(line_obj, ensure_ascii=False) + "\n"
        with _MATCHER_ERROR_JSONL_LOCK:
            rec = _plugin_run_bot_bucket(sid)
            log = rec.setdefault("matcher_error_log", [])
            if not isinstance(log, list):
                rec["matcher_error_log"] = []
                log = rec["matcher_error_log"]
            log.append(entry)
            while len(log) > _MATCHER_ERROR_LOG_CAP:
                log.pop(0)
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("a", encoding="utf-8") as f:
                f.write(line)
    except Exception:  # noqa: BLE001
        pass


def _rewrite_matcher_durations_jsonl() -> None:
    """用各账号进程内缓冲覆写 jsonl。"""

    path = pb_webui_data_dir() / "matcher_durations.jsonl"
    lines: list[str] = []
    for sid, rec in _PLUGIN_RUN_STATS.items():
        if not isinstance(rec, dict):
            continue
        raw = rec.get("matcher_duration_log")
        if not isinstance(raw, list):
            continue
        for it in raw:
            if not isinstance(it, dict):
                continue
            line_obj = {
                "self_id": str(sid),
                "at": int(it.get("at") or 0),
                "plugin": str(it.get("plugin") or ""),
                "duration_ms": _duration_ms_float(it.get("duration_ms") or 0),
                "had_error": bool(it.get("had_error")),
            }
            lines.append(json.dumps(line_obj, ensure_ascii=False))
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".jsonl.tmp")
    tmp.write_text(("\n".join(lines) + ("\n" if lines else "")), encoding="utf-8")
    tmp.replace(path)


def _load_matcher_duration_logs_from_disk() -> None:
    """启动时从 jsonl 恢复各账号最近 _MATCHER_DURATION_LOG_CAP 条单次耗时。"""

    path = pb_webui_data_dir() / "matcher_durations.jsonl"
    if not path.exists():
        return
    by_sid: dict[str, list[dict[str, Any]]] = defaultdict(list)
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(obj, dict):
            continue
        sid = str(obj.get("self_id") or "").strip()
        if not sid:
            continue
        try:
            at = int(obj.get("at") or 0)
        except (TypeError, ValueError):
            at = 0
        try:
            duration_ms = _duration_ms_float(obj.get("duration_ms") or 0)
        except (TypeError, ValueError):
            duration_ms = 0.0
        by_sid[sid].append({
            "at": at,
            "plugin": str(obj.get("plugin") or ""),
            "duration_ms": duration_ms,
            "had_error": bool(obj.get("had_error")),
        })
    cap = _MATCHER_DURATION_LOG_CAP
    worker_assigned: set[str] = set()
    try:
        if shard_hub_console():
            from pallas.core.platform.shard.registry.store import get_shard_registry

            worker_assigned = {str(k).strip() for k in get_shard_registry().assignments if str(k).strip()}
    except Exception:  # noqa: BLE001
        pass
    for sid, entries in by_sid.items():
        sid = str(sid).strip()
        if not sid or sid in worker_assigned:
            continue
        rec = _plugin_run_bot_bucket(sid)
        rec["matcher_duration_log"] = entries[-cap:]
        enforce_matcher_duration_log_limits(rec["matcher_duration_log"])


def trim_matcher_duration_log_to_local_day(log: list[dict[str, Any]], day: str) -> None:
    """原地删除非 day 自然日的单次耗时。"""
    if not isinstance(log, list):
        return
    day_key = str(day).strip()[:10]
    if len(day_key) < 10:
        return
    i = 0
    while i < len(log):
        it = log[i]
        if not isinstance(it, dict):
            log.pop(i)
            continue
        try:
            at = int(it.get("at") or 0)
        except (TypeError, ValueError):
            at = 0
        if at <= 0 or time.strftime("%Y-%m-%d", time.localtime(at)) != day_key:
            log.pop(i)
        else:
            i += 1


def enforce_matcher_duration_log_limits(log: list[dict[str, Any]]) -> None:
    """单账号缓冲：总条数与单插件条数上限。"""
    if not isinstance(log, list):
        return
    while len(log) > _MATCHER_DURATION_LOG_CAP:
        log.pop(0)
    per_cap = _MATCHER_DURATION_LOG_PER_PLUGIN_CAP
    if per_cap <= 0:
        return
    while True:
        counts: dict[str, int] = {}
        for it in log:
            if not isinstance(it, dict):
                continue
            p = str(it.get("plugin") or "").strip()
            if p:
                counts[p] = counts.get(p, 0) + 1
        over = {p for p, c in counts.items() if c > per_cap}
        if not over:
            break
        drop_idx = -1
        for i, it in enumerate(log):
            if not isinstance(it, dict):
                continue
            p = str(it.get("plugin") or "").strip()
            if p in over:
                drop_idx = i
                break
        if drop_idx < 0:
            break
        log.pop(drop_idx)


def _append_matcher_duration_log(
    sid: str,
    plugin: str,
    duration_ms: int | float,
    *,
    had_error: bool,
) -> None:
    """进程内环形缓冲；单进程/hub 另写 jsonl；分片 worker 由 stats 文件周期刷盘。"""

    global _MATCHER_DURATION_LOG_DIRTY

    entry: dict[str, Any] = {
        "at": int(time.time()),
        "plugin": plugin,
        "duration_ms": _duration_ms_float(duration_ms),
        "had_error": bool(had_error),
    }
    try:
        rec = _plugin_run_bot_bucket(sid)
        log = rec.setdefault("matcher_duration_log", [])
        if not isinstance(log, list):
            rec["matcher_duration_log"] = []
            log = rec["matcher_duration_log"]
        log.append(entry)
        enforce_matcher_duration_log_limits(log)
        if shard_worker_console():
            return
        if not shard_hub_console():
            _MATCHER_DURATION_LOG_DIRTY = True
            return
        with _MATCHER_DURATION_JSONL_LOCK:
            _rewrite_matcher_durations_jsonl()
    except Exception:  # noqa: BLE001
        pass


def _flush_matcher_duration_log_if_dirty() -> None:
    global _MATCHER_DURATION_LOG_DIRTY

    if not _MATCHER_DURATION_LOG_DIRTY:
        return
    with _MATCHER_DURATION_JSONL_LOCK:
        if not _MATCHER_DURATION_LOG_DIRTY:
            return
        _rewrite_matcher_durations_jsonl()
        _MATCHER_DURATION_LOG_DIRTY = False


def _matcher_duration_log_public(
    rec: dict[str, Any],
    *,
    limit: int = _MATCHER_DURATION_LOG_CAP,
) -> list[dict[str, Any]]:
    raw = rec.get("matcher_duration_log")
    if not isinstance(raw, list) or not raw:
        return []
    day_filter = ""
    try:
        if shard_hub_console():
            day_filter = time.strftime("%Y-%m-%d", time.localtime())
    except Exception:  # noqa: BLE001
        pass
    out: list[dict[str, Any]] = []
    for it in reversed(raw[-limit:]):
        if not isinstance(it, dict):
            continue
        try:
            at = int(it.get("at") or 0)
        except (TypeError, ValueError):
            at = 0
        if day_filter and at > 0 and time.strftime("%Y-%m-%d", time.localtime(at)) != day_filter:
            continue
        try:
            duration_ms = _duration_ms_float(it.get("duration_ms") or 0)
        except (TypeError, ValueError):
            duration_ms = 0.0
        out.append({
            "at": at,
            "plugin": str(it.get("plugin") or ""),
            "duration_ms": duration_ms,
            "had_error": bool(it.get("had_error")),
        })
    return out


def _matcher_error_log_public(rec: dict[str, Any], *, limit: int = 30, tb_limit: int = 4000) -> list[dict[str, Any]]:
    raw = rec.get("matcher_error_log")
    if not isinstance(raw, list) or not raw:
        return []
    out: list[dict[str, Any]] = []
    for it in raw[-limit:]:
        if not isinstance(it, dict):
            continue
        tb = str(it.get("traceback") or "")
        if len(tb) > tb_limit:
            tb = tb[:tb_limit] + "\n…(truncated)"
        try:
            at = int(it.get("at") or 0)
        except (TypeError, ValueError):
            at = 0
        out.append({
            "at": at,
            "plugin": str(it.get("plugin") or ""),
            "exc_type": str(it.get("exc_type") or ""),
            "message": str(it.get("message") or "")[:2000],
            "traceback": tb,
        })
    return out


def _dotted_module_short_name(module_name: str) -> str:
    parts = str(module_name).split(".")
    for part in reversed(parts):
        if part and part != "__init__":
            return part
    return str(module_name or "") or "unknown"


def _tb_and_exc_type_from_log_record(record: Any) -> tuple[str, str, str]:
    from pallas.core.platform.shard.logs.errors import parse_log_error_from_record

    return parse_log_error_from_record("", record)


def _append_console_log_error(entry: dict[str, Any]) -> None:

    path = pb_webui_data_dir() / "log_errors.jsonl"
    line_obj = {k: v for k, v in entry.items() if k != "raw_line"}
    line = json.dumps(line_obj, ensure_ascii=False) + "\n"
    try:
        with _LOG_ERROR_JSONL_LOCK:
            buf = entry.copy()
            buf.pop("raw_line", None)
            _LOG_ERROR_BUFFER.append(buf)
            while len(_LOG_ERROR_BUFFER) > _LOG_ERROR_LOG_CAP:
                _LOG_ERROR_BUFFER.pop(0)
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("a", encoding="utf-8") as f:
                f.write(line)
    except Exception:  # noqa: BLE001
        pass


def _append_log_error_from_sink(text: str, record: Any) -> None:
    from pallas.core.platform.shard.logs.errors import parse_log_error_from_record

    exc_type, msg, tb = parse_log_error_from_record(text, record)
    try:
        full_name = str(record["name"] or "")
    except Exception:  # noqa: BLE001
        full_name = ""
    plugin = _dotted_module_short_name(full_name)
    if len(tb) > _LOG_ERROR_TB_MAX:
        tb = tb[:_LOG_ERROR_TB_MAX] + "\n…(truncated)"
    if len(msg) > _LOG_ERROR_MSG_MAX:
        msg = msg[:_LOG_ERROR_MSG_MAX] + "…"
    if not msg.strip():
        msg = (text or "")[:_LOG_ERROR_MSG_MAX]
        if len(text or "") > _LOG_ERROR_MSG_MAX:
            msg = msg + "…"
    entry: dict[str, Any] = {
        "at": int(time.time()),
        "plugin": plugin,
        "exc_type": exc_type,
        "message": msg,
        "traceback": tb,
        "raw_line": text,
    }
    _append_console_log_error(entry)
    try:
        if shard_hub_console():
            from pallas.core.platform.shard.logs.errors import append_shard_log_error, log_stem_for_shard
            from pallas.core.platform.shard.registry.config import get_shard_registry_settings

            s = get_shard_registry_settings()
            stem = log_stem_for_shard(role=s.role, shard_id=s.shard_id)
            shard_entry = {k: v for k, v in entry.items() if k != "raw_line"}
            append_shard_log_error(shard_entry, stem=stem)
    except Exception:
        pass


def _normalize_log_error_entry(it: dict[str, Any], *, tb_limit: int) -> dict[str, Any] | None:
    if not isinstance(it, dict):
        return None
    tb = str(it.get("traceback") or "")
    if tb_limit > 0 and len(tb) > tb_limit:
        tb = tb[:tb_limit] + "\n…(truncated)"
    try:
        at = int(it.get("at") or 0)
    except (TypeError, ValueError):
        at = 0
    return {
        "at": at,
        "plugin": str(it.get("plugin") or ""),
        "exc_type": str(it.get("exc_type") or ""),
        "message": str(it.get("message") or "")[:2000],
        "traceback": tb,
    }


def _log_error_entry_matches_source(entry: dict[str, Any], source: str | None) -> bool:
    want = (source or "all").strip() or "all"
    if want == "all":
        return True
    plugin = str(entry.get("plugin") or "")
    if want == "hub":
        return not plugin.startswith("worker-")
    if want.startswith("worker-"):
        return plugin == want or plugin.startswith(f"{want}/")
    return True


def _log_error_log_meta() -> dict[str, Any]:
    sharded = False
    sources = ["hub"]
    try:
        if shard_hub_console():
            sharded = True
            from pallas.core.platform.shard.logs.view import list_shard_log_sources

            sources = list_shard_log_sources()
    except Exception:
        pass
    return {"sharded_log_errors": sharded, "log_error_sources": sources}


_LOG_ERROR_PUBLIC_SNAPSHOT: list[dict[str, Any]] | None = None
_LOG_ERROR_PUBLIC_SNAPSHOT_KEY: tuple[Any, ...] | None = None
_LOG_ERROR_PUBLIC_SNAPSHOT_EXP: float = 0.0
_LOG_ERROR_PUBLIC_SNAPSHOT_TTL_SEC = 2.5


def _invalidate_log_error_public_cache() -> None:
    global _LOG_ERROR_PUBLIC_SNAPSHOT, _LOG_ERROR_PUBLIC_SNAPSHOT_KEY, _LOG_ERROR_PUBLIC_SNAPSHOT_EXP
    _LOG_ERROR_PUBLIC_SNAPSHOT = None
    _LOG_ERROR_PUBLIC_SNAPSHOT_KEY = None
    _LOG_ERROR_PUBLIC_SNAPSHOT_EXP = 0.0


def _log_errors_payload(
    *,
    source: str | None = None,
    tb_limit: int = 0,
    limit: int = 120,
) -> dict[str, Any]:
    return {
        "log_error_log": _log_error_log_public(source=source, tb_limit=tb_limit, limit=limit),
        **_log_error_log_meta(),
    }


def _log_error_log_public(
    *,
    limit: int = 30,
    tb_limit: int = 0,
    source: str | None = None,
) -> list[dict[str, Any]]:
    global _LOG_ERROR_PUBLIC_SNAPSHOT, _LOG_ERROR_PUBLIC_SNAPSHOT_KEY, _LOG_ERROR_PUBLIC_SNAPSHOT_EXP
    src = (source or "all").strip() or "all"
    cap = max(1, int(limit))
    cache_key = (src, int(tb_limit), cap)
    now = time.monotonic()
    if (
        _LOG_ERROR_PUBLIC_SNAPSHOT_KEY == cache_key
        and _LOG_ERROR_PUBLIC_SNAPSHOT is not None
        and now < _LOG_ERROR_PUBLIC_SNAPSHOT_EXP
    ):
        return [dict(it) for it in _LOG_ERROR_PUBLIC_SNAPSHOT if isinstance(it, dict)]

    with _LOG_ERROR_JSONL_LOCK:
        raw = list(_LOG_ERROR_BUFFER)
    merged: list[dict[str, Any]] = [dict(it) for it in raw if isinstance(it, dict)]
    try:
        if shard_hub_console():
            from pallas.core.platform.shard.logs.view import collect_cluster_log_errors

            cluster_limit = max(cap * 2, 40)
            per_file = min(600, max(cap * 6, 80))
            merged.extend(
                collect_cluster_log_errors(per_file=per_file, limit=cluster_limit),
            )
    except Exception:
        pass
    if not merged:
        _LOG_ERROR_PUBLIC_SNAPSHOT = []
        _LOG_ERROR_PUBLIC_SNAPSHOT_KEY = cache_key
        _LOG_ERROR_PUBLIC_SNAPSHOT_EXP = now + _LOG_ERROR_PUBLIC_SNAPSHOT_TTL_SEC
        return []
    seen: set[tuple[str, str, str]] = set()
    bucket: list[dict[str, Any]] = []
    for it in merged:
        norm = _normalize_log_error_entry(it, tb_limit=tb_limit)
        if norm is None:
            continue
        key = (norm["plugin"], norm["exc_type"], norm["message"][:300])
        if key in seen:
            continue
        seen.add(key)
        if not _log_error_entry_matches_source(norm, source):
            continue
        bucket.append(norm)
    bucket.sort(key=lambda x: int(x.get("at") or 0))
    out = bucket[-cap:]
    _LOG_ERROR_PUBLIC_SNAPSHOT = [dict(it) for it in out]
    _LOG_ERROR_PUBLIC_SNAPSHOT_KEY = cache_key
    _LOG_ERROR_PUBLIC_SNAPSHOT_EXP = now + _LOG_ERROR_PUBLIC_SNAPSHOT_TTL_SEC
    return [dict(it) for it in out]


def _cleanup_log_error_archives_sync() -> None:

    path = pb_webui_data_dir() / "log_errors.jsonl"
    with _LOG_ERROR_JSONL_LOCK:
        try:
            if path.exists():
                path.unlink()
        except OSError as e:
            logger.warning("Pallas-Bot 控制台: 删除 log_errors.jsonl 失败: {}", str(e))
        _LOG_ERROR_BUFFER.clear()
    _invalidate_log_error_public_cache()


def _cleanup_log_errors_manual_sync() -> dict[str, Any]:
    """清空日志报错归档。"""
    _cleanup_log_error_archives_sync()
    sharded_errors = False
    try:
        if shard_hub_console():
            from pallas.core.platform.shard.logs.errors import cleanup_shard_error_archives_sync

            cleanup_shard_error_archives_sync()
            sharded_errors = True
    except Exception:
        pass
    drop_read_cache(("plugin-run-stats:", "log-errors:", "home-overview"))
    return {"cleared": True, "sharded_errors": sharded_errors}


async def _scheduled_cleanup_matcher_error_logs() -> None:
    """每日 4:00 清理 Matcher 异常与日志 ERROR 归档。"""

    err_path = pb_webui_data_dir() / "matcher_errors.jsonl"
    dur_path = pb_webui_data_dir() / "matcher_durations.jsonl"
    with _MATCHER_ERROR_JSONL_LOCK:
        try:
            if err_path.exists():
                err_path.unlink()
        except OSError as e:
            logger.warning("Pallas-Bot 控制台: 删除 matcher_errors.jsonl 失败: {}", str(e))
        for rec in _PLUGIN_RUN_STATS.values():
            if isinstance(rec, dict):
                rec["matcher_error_log"] = []
    with _MATCHER_DURATION_JSONL_LOCK:
        try:
            if dur_path.exists():
                dur_path.unlink()
        except OSError as e:
            logger.warning("Pallas-Bot 控制台: 删除 matcher_durations.jsonl 失败: {}", str(e))
        for rec in _PLUGIN_RUN_STATS.values():
            if isinstance(rec, dict):
                rec["matcher_duration_log"] = []
    _cleanup_log_error_archives_sync()
    try:
        if shard_hub_console():
            from pallas.core.platform.shard.console_stats import iter_worker_shard_ids, trim_worker_duration_logs_sync
            from pallas.core.platform.shard.logs.errors import cleanup_shard_error_archives_sync

            cleanup_shard_error_archives_sync()
            from pallas.core.platform.shard.logs.view import cleanup_stale_shard_log_files

            cleanup_stale_shard_log_files()
            for wid in iter_worker_shard_ids():
                trim_worker_duration_logs_sync(shard_id=wid, cap=0)
    except Exception:
        pass
    drop_read_cache(("plugin-run-stats:", "log-errors:", "home-overview"))
    logger.info(
        "Pallas-Bot 控制台: 控制台异常记录已按计划清理（每日 4:00，"
        "matcher_errors.jsonl、matcher_durations.jsonl、log_errors.jsonl、分片 errors/*.jsonl 与进程内缓冲）"
    )


def _matcher_hist_bump(sid: str, plugin: str, had_error: bool, *, duration_ms: int | float = 0) -> None:
    """Matcher 执行按时间桶、按插件名记录。"""
    pname = str(plugin).strip() or "_"
    dur = _duration_ms_float(duration_ms)
    rec = _plugin_run_bot_bucket(sid)
    hist = rec.setdefault("matcher_hist", [])
    if not isinstance(hist, list):
        rec["matcher_hist"] = []
        hist = rec["matcher_hist"]
    now = int(time.time())
    bucket = _hist_bucket_start_local(now, _API_HIST_BUCKET_SEC)
    cutoff = bucket - (_API_HIST_MAX_BUCKETS - 1) * _API_HIST_BUCKET_SEC
    i = 0
    while i < len(hist):
        h = hist[i]
        if not isinstance(h, dict):
            hist.pop(i)
            continue
        try:
            at = int(h.get("at") or 0)
        except (TypeError, ValueError):
            hist.pop(i)
            continue
        if at < cutoff:
            hist.pop(i)
        else:
            i += 1
    if hist and isinstance(hist[-1], dict):
        try:
            last_at = int(hist[-1].get("at") or 0)
        except (TypeError, ValueError):
            last_at = 0
        if last_at == bucket:
            plugs = hist[-1].setdefault("plugins", {})
            if not isinstance(plugs, dict):
                hist[-1]["plugins"] = {}
                plugs = hist[-1]["plugins"]
            plugs[pname] = int(plugs.get(pname, 0)) + 1
            durs = hist[-1].setdefault("plugin_duration_ms", {})
            if not isinstance(durs, dict):
                hist[-1]["plugin_duration_ms"] = {}
                durs = hist[-1]["plugin_duration_ms"]
            durs[pname] = _round_duration_ms(_duration_ms_float(durs.get(pname, 0)) + dur)
            if had_error:
                errs = hist[-1].setdefault("plugin_errors", {})
                if not isinstance(errs, dict):
                    hist[-1]["plugin_errors"] = {}
                    errs = hist[-1]["plugin_errors"]
                errs[pname] = int(errs.get(pname, 0)) + 1
            return
    entry: dict[str, Any] = {"at": bucket, "plugins": {pname: 1}, "plugin_duration_ms": {pname: dur}}
    if had_error:
        entry["plugin_errors"] = {pname: 1}
    hist.append(entry)


def _matcher_hist_series_public(rec: dict[str, Any], *, limit: int = _HIST_PLUGIN_SERIES_MAX) -> dict[str, Any]:
    raw = rec.get("matcher_hist")
    by_plugin = rec.get("by_plugin")
    ranked: list[str] = []
    if isinstance(by_plugin, dict) and by_plugin:
        ranked = sorted(
            by_plugin.keys(),
            key=lambda k: (
                -int((by_plugin.get(k) or {}).get("day_runs", 0) if isinstance(by_plugin.get(k), dict) else 0)
            ),
        )
        ranked = [str(k) for k in ranked if str(k).strip() and not _is_console_stats_excluded_plugin(str(k))][:limit]
    if not ranked and isinstance(raw, list):
        acc: set[str] = set()
        for it in raw:
            plugs = it.get("plugins") if isinstance(it, dict) else None
            if isinstance(plugs, dict):
                acc.update(str(k) for k in plugs if str(k).strip())
        ranked = sorted(acc)[:limit]
    if not isinstance(raw, list) or not raw or not ranked:
        return {"matcher_runs_by_plugin": [], "matcher_errors_by_plugin": []}
    buckets = sorted(
        [x for x in raw if isinstance(x, dict) and "at" in x],
        key=lambda x: int(x.get("at") or 0),
    )
    runs_out: list[dict[str, Any]] = []
    err_out: list[dict[str, Any]] = []
    for pname in ranked:
        r_pts: list[dict[str, Any]] = []
        e_pts: list[dict[str, Any]] = []
        for it in buckets:
            try:
                at = int(it["at"])
            except (TypeError, ValueError, KeyError):
                continue
            plugs = it.get("plugins")
            r = 0
            if isinstance(plugs, dict):
                try:
                    r = int(plugs.get(pname, 0))
                except (TypeError, ValueError):
                    r = 0
            errs = it.get("plugin_errors")
            e = 0
            if isinstance(errs, dict):
                try:
                    e = int(errs.get(pname, 0))
                except (TypeError, ValueError):
                    e = 0
            r_pts.append({"at": at, "total": r})
            e_pts.append({"at": at, "total": e})
        if sum(int(x.get("total", 0) or 0) for x in r_pts):
            runs_out.append({"plugin": pname, "points": r_pts})
        if sum(int(x.get("total", 0) or 0) for x in e_pts):
            err_out.append({"plugin": pname, "points": e_pts})
    return {"matcher_runs_by_plugin": runs_out, "matcher_errors_by_plugin": err_out}


def _matcher_duration_hist_series_public(
    rec: dict[str, Any],
    *,
    limit: int = _HIST_PLUGIN_SERIES_MAX,
) -> dict[str, Any]:
    """各插件 Matcher 耗时按时间桶累计；与 matcher_runs 同桶可算平均耗时。"""
    raw = rec.get("matcher_hist")
    ranked: list[str] = []
    by_plugin = rec.get("by_plugin")
    if isinstance(by_plugin, dict) and by_plugin:

        def _day_dur_sum(plugin_key: str) -> float:
            prow = by_plugin.get(plugin_key)
            if not isinstance(prow, dict):
                return 0.0
            return _duration_ms_float(prow.get("day_duration_ms_sum", 0))

        ranked = sorted(by_plugin.keys(), key=lambda k: -_day_dur_sum(k))
        ranked = [str(k) for k in ranked if str(k).strip() and not _is_console_stats_excluded_plugin(str(k))][:limit]
    if not ranked and isinstance(raw, list):
        acc: set[str] = set()
        for it in raw:
            if not isinstance(it, dict):
                continue
            durs = it.get("plugin_duration_ms")
            if isinstance(durs, dict):
                acc.update(str(k) for k in durs if str(k).strip())
        ranked = sorted(acc)[:limit]
    if not isinstance(raw, list) or not raw or not ranked:
        return {"matcher_duration_ms_by_plugin": [], "matcher_avg_duration_ms_by_plugin": []}
    buckets = sorted(
        [x for x in raw if isinstance(x, dict) and "at" in x],
        key=lambda x: int(x.get("at") or 0),
    )
    ms_out: list[dict[str, Any]] = []
    avg_out: list[dict[str, Any]] = []
    for pname in ranked:
        ms_pts: list[dict[str, Any]] = []
        avg_pts: list[dict[str, Any]] = []
        for it in buckets:
            try:
                at = int(it["at"])
            except (TypeError, ValueError, KeyError):
                continue
            plugs = it.get("plugins")
            runs = 0
            if isinstance(plugs, dict):
                try:
                    runs = int(plugs.get(pname, 0))
                except (TypeError, ValueError):
                    runs = 0
            durs = it.get("plugin_duration_ms")
            ms = 0.0
            if isinstance(durs, dict):
                ms = _duration_ms_float(durs.get(pname, 0))
            if ms <= 0 and runs <= 0:
                continue
            ms_pts.append({"at": at, "total": ms})
            if runs > 0 and ms > 0:
                avg_pts.append({"at": at, "total": _round_duration_ms(ms / runs)})
        if sum(float(x.get("total", 0) or 0) for x in ms_pts):
            ms_out.append({"plugin": pname, "points": ms_pts})
        if sum(float(x.get("total", 0) or 0) for x in avg_pts):
            avg_out.append({"plugin": pname, "points": avg_pts})
    return {
        "matcher_duration_ms_by_plugin": ms_out,
        "matcher_avg_duration_ms_by_plugin": avg_out,
    }


def _init_plugin_run_tracking() -> None:
    """run_pre/postprocessor：Matcher 墙钟耗时与次数。"""
    global _PLUGIN_RUN_TRACKING_INIT
    if _PLUGIN_RUN_TRACKING_INIT:
        return
    _PLUGIN_RUN_TRACKING_INIT = True

    if shard_worker_console():
        _restore_worker_console_stats_from_shard_file()
    elif not _restore_unified_console_stats_from_live_file():
        _load_matcher_duration_logs_from_disk()

    from nonebot.message import run_postprocessor, run_preprocessor

    @run_preprocessor
    async def _mark_plugin_matcher_run_start(
        matcher: Matcher,
        bot: BaseBot,
        _event: Event,
    ) -> None:
        plugin = _plugin_short_name_from_matcher(matcher).strip()
        if not plugin or _is_console_stats_excluded_plugin(plugin):
            return
        sid = str(getattr(bot, "self_id", "") or "").strip()
        if not sid:
            return
        mark_matcher_run_started(matcher)

    @run_postprocessor
    async def _count_plugin_matcher_run(
        matcher: Matcher,
        exception: Exception | None,
        bot: BaseBot,
        _event: Event,
    ) -> None:
        plugin = _plugin_short_name_from_matcher(matcher).strip()
        if not plugin or _is_console_stats_excluded_plugin(plugin):
            return
        sid = str(getattr(bot, "self_id", "") or "").strip()
        if not sid:
            return
        started = take_matcher_run_started(matcher)
        elapsed_ms = _matcher_elapsed_ms(started)
        try:
            row = _plugin_run_plugin_row(sid, plugin)
            row["runs"] = int(row["runs"]) + 1
            row["day_runs"] = int(row["day_runs"]) + 1
            if exception is not None:
                row["errors"] = int(row["errors"]) + 1
                row["day_errors"] = int(row["day_errors"]) + 1
                _append_matcher_error_log(sid, plugin, exception)
            _record_plugin_run_duration(sid, plugin, elapsed_ms)
            _append_matcher_duration_log(
                sid,
                plugin,
                elapsed_ms,
                had_error=exception is not None,
            )
            _matcher_hist_bump(
                sid,
                plugin,
                exception is not None,
                duration_ms=elapsed_ms,
            )
        except Exception:  # noqa: BLE001
            pass


def _plugin_run_stats_bot_row(
    *,
    sid: str,
    connection_key: str,
    bucket: dict[str, Any],
    include_hist: bool,
) -> dict[str, Any]:
    by_plugin = bucket.get("by_plugin", {}) if isinstance(bucket, dict) else {}
    plugins_list: list[dict[str, Any]] = []
    br = be = brt = bet = 0
    for pname, prow in by_plugin.items():
        if not isinstance(prow, dict) or _is_console_stats_excluded_plugin(str(pname)):
            continue
        r = int(prow.get("runs", 0))
        e = int(prow.get("errors", 0))
        rt = int(prow.get("day_runs", 0))
        et = int(prow.get("day_errors", 0))
        dsum = _duration_ms_float(prow.get("duration_ms_sum", 0))
        dcnt = int(prow.get("duration_count", 0))
        dmax = _duration_ms_float(prow.get("duration_ms_max", 0))
        dsum_t = _duration_ms_float(prow.get("day_duration_ms_sum", 0))
        dcnt_t = int(prow.get("day_duration_count", 0))
        dmax_t = _duration_ms_float(prow.get("day_duration_ms_max", 0))
        plugins_list.append({
            "name": str(pname),
            "runs": r,
            "runs_today": rt,
            "errors": e,
            "errors_today": et,
            "avg_duration_ms": _avg_duration_ms(dsum, dcnt),
            "max_duration_ms": dmax if dcnt > 0 else None,
            "avg_duration_ms_today": _avg_duration_ms(dsum_t, dcnt_t),
            "max_duration_ms_today": dmax_t if dcnt_t > 0 else None,
        })
        br += r
        be += e
        brt += rt
        bet += et
    plugins_list.sort(key=lambda x: (-int(x["runs_today"]), -int(x["runs"]), str(x["name"])))
    if include_hist and isinstance(bucket, dict):
        hist_pack = _matcher_hist_series_public(bucket)
        dur_pack = _matcher_duration_hist_series_public(bucket)
    else:
        hist_pack = _EMPTY_MATCHER_HIST_SERIES
        dur_pack = _EMPTY_MATCHER_DUR_HIST_SERIES
    err_log = _matcher_error_log_public(bucket if isinstance(bucket, dict) else {})
    dur_log = _matcher_duration_log_public(bucket if isinstance(bucket, dict) else {})
    return {
        "self_id": sid,
        "connection_key": connection_key,
        "runs": br,
        "errors": be,
        "runs_today": brt,
        "errors_today": bet,
        "plugins": plugins_list,
        "matcher_runs_by_plugin": hist_pack["matcher_runs_by_plugin"],
        "matcher_errors_by_plugin": hist_pack["matcher_errors_by_plugin"],
        "matcher_duration_ms_by_plugin": dur_pack["matcher_duration_ms_by_plugin"],
        "matcher_avg_duration_ms_by_plugin": dur_pack["matcher_avg_duration_ms_by_plugin"],
        "matcher_error_log": err_log,
        "matcher_duration_log": dur_log,
        "matcher_duration_log_cap": _MATCHER_DURATION_LOG_CAP,
        "matcher_duration_log_per_plugin_cap": _MATCHER_DURATION_LOG_PER_PLUGIN_CAP,
    }


def _plugin_run_stats_overview(
    *,
    self_id: str | None,
    log_source: str | None = None,
    tb_limit: int = 0,
    include_log_errors: bool = True,
) -> dict[str, Any]:
    from .social_api import _is_onebot_v11_bot

    rows_out: list[dict[str, Any]] = []
    total_runs = 0
    total_errors = 0
    total_runs_today = 0
    total_errors_today = 0
    want = str(self_id).strip() if self_id else None

    def _append_row(row: dict[str, Any]) -> None:
        nonlocal total_runs, total_errors, total_runs_today, total_errors_today
        rows_out.append(row)
        total_runs += int(row.get("runs", 0))
        total_errors += int(row.get("errors", 0))
        total_runs_today += int(row.get("runs_today", 0))
        total_errors_today += int(row.get("errors_today", 0))

    if shard_hub_console():
        from pallas.core.platform.shard.console_stats import load_cluster_console_stats_by_sid
        from pallas.core.platform.shard.presence import read_presence_bots

        cluster = load_cluster_console_stats_by_sid()
        seen: set[str] = set()

        def _sort_key(s: str) -> tuple[int, str]:
            return (int(s), s) if s.isdigit() else (10**18, s)

        for sid in sorted(read_presence_bots().keys(), key=_sort_key):
            if want and sid != want:
                continue
            rec = read_presence_bots()[sid]
            bucket = cluster.get(sid, {})
            if not isinstance(bucket, dict):
                bucket = {}
            _append_row(
                _plugin_run_stats_bot_row(
                    sid=sid,
                    connection_key=str(rec.get("connection_key") or sid),
                    bucket=bucket,
                    include_hist=True,
                )
            )
            seen.add(sid)
        for key, bot in get_bots().items():
            sid = str(getattr(bot, "self_id", "") or "").strip()
            if not sid or sid in seen:
                continue
            if want and sid != want:
                continue
            if not _is_onebot_v11_bot(bot):
                continue
            _plugin_run_bot_bucket(sid)
            bucket = _PLUGIN_RUN_STATS.get(sid, {})
            _append_row(
                _plugin_run_stats_bot_row(
                    sid=sid,
                    connection_key=str(key),
                    bucket=bucket if isinstance(bucket, dict) else {},
                    include_hist=True,
                )
            )
            seen.add(sid)
        if want and want not in seen:
            bucket = cluster.get(want, {})
            _append_row(
                _plugin_run_stats_bot_row(
                    sid=want,
                    connection_key=want,
                    bucket=bucket if isinstance(bucket, dict) else {},
                    include_hist=True,
                )
            )
    else:
        for key, bot in get_bots().items():
            sid = str(getattr(bot, "self_id", "") or "").strip()
            if not sid:
                continue
            if want and sid != want:
                continue
            if not _is_onebot_v11_bot(bot):
                continue
            _plugin_run_bot_bucket(sid)
            bucket = _PLUGIN_RUN_STATS.get(sid, {})
            _append_row(
                _plugin_run_stats_bot_row(
                    sid=sid,
                    connection_key=str(key),
                    bucket=bucket if isinstance(bucket, dict) else {},
                    include_hist=True,
                )
            )
    payload: dict[str, Any] = {
        "total_runs": total_runs,
        "total_errors": total_errors,
        "total_runs_today": total_runs_today,
        "total_errors_today": total_errors_today,
        "matcher_calls_history_bucket_sec": _API_HIST_BUCKET_SEC,
        "matcher_calls_history_max_buckets": _API_HIST_MAX_BUCKETS,
        "bots": rows_out,
        **_log_error_log_meta(),
    }
    if include_log_errors:
        payload["log_error_log"] = _log_error_log_public(source=log_source, tb_limit=tb_limit)
    return payload


def _console_daily_stats_payload(
    *,
    self_id: str | None,
    start: str | None,
    end: str | None,
) -> dict[str, Any]:
    """按自然日汇总：消息收/发与 Matcher 次数。"""
    from datetime import date, timedelta

    from packages.pb_webui import daily_stats_store

    clock_today = time.strftime("%Y-%m-%d", time.localtime())
    today_d = date.fromisoformat(clock_today)
    end_d = today_d
    if end:
        try:
            end_d = date.fromisoformat(str(end).strip()[:10])
        except ValueError:
            end_d = today_d
    start_d = end_d - timedelta(days=89)
    if start:
        try:
            start_d = date.fromisoformat(str(start).strip()[:10])
        except ValueError:
            pass
    if start_d > end_d:
        start_d, end_d = end_d, start_d
    sid_f = str(self_id).strip() if self_id else None
    if sid_f == "":
        sid_f = None
    rows, s1, s2 = daily_stats_store.load_range(
        self_id=sid_f,
        start_day=start_d.isoformat(),
        end_day=end_d.isoformat(),
    )
    by_key: dict[tuple[str, str], dict[str, Any]] = {(r["date"], r["self_id"]): dict(r) for r in rows}
    live_out: dict[str, dict[str, int]] = {}

    shard_cluster_sids: set[str] = set()
    if shard_hub_console():
        from pallas.core.platform.shard.console_stats import load_cluster_console_stats_by_sid

        for sid, blob in load_cluster_console_stats_by_sid().items():
            sid = str(sid).strip()
            if not sid or (sid_f is not None and sid != sid_f):
                continue
            shard_cluster_sids.add(sid)
            msg = blob.get("msg") if isinstance(blob, dict) else {}
            dr = int(msg.get("day_received", 0)) if isinstance(msg, dict) else 0
            ds = int(msg.get("day_sent", 0)) if isinstance(msg, dict) else 0
            ac = int(msg.get("day_api_total", 0)) if isinstance(msg, dict) else 0
            mr = 0
            bp = blob.get("by_plugin") if isinstance(blob, dict) else {}
            if isinstance(bp, dict):
                for prow in bp.values():
                    if isinstance(prow, dict):
                        mr += int(prow.get("day_runs", 0))
            live_out[sid] = {"received": dr, "sent": ds, "matcher_runs": mr, "api_calls": ac}
            if start_d <= today_d <= end_d:
                daily_stats_store.merge_today_row(
                    by_key,
                    day=clock_today,
                    self_id=sid,
                    received=dr,
                    sent=ds,
                    matcher_runs=mr,
                    api_calls=ac,
                )
    for sid in set(_MSG_STATS.keys()) | set(_PLUGIN_RUN_STATS.keys()):
        sid = str(sid).strip()
        if not sid:
            continue
        if sid_f is not None and sid != sid_f:
            continue
        if shard_hub_console() and sid in shard_cluster_sids:
            continue
        _rollover_console_day_if_needed(sid, clock_today)
        mem = _MSG_STATS.get(sid)
        dr = int(mem.get("day_received", 0)) if isinstance(mem, dict) else 0
        ds = int(mem.get("day_sent", 0)) if isinstance(mem, dict) else 0
        ac = int(mem.get("day_api_total", 0)) if isinstance(mem, dict) else 0
        mr = _sum_matcher_day_runs(sid)
        live_out[sid] = {"received": dr, "sent": ds, "matcher_runs": mr, "api_calls": ac}
        if start_d <= today_d <= end_d:
            daily_stats_store.merge_today_row(
                by_key,
                day=clock_today,
                self_id=sid,
                received=dr,
                sent=ds,
                matcher_runs=mr,
                api_calls=ac,
            )
    merged = sorted(by_key.values(), key=itemgetter("date", "self_id"))
    live_active: dict[str, set[str]] = {}
    for sid, mem in _MSG_STATS.items():
        key = str(sid).strip()
        if not key or (sid_f is not None and key != sid_f):
            continue
        if isinstance(mem, dict):
            live_active[key] = _day_active_groups_from_mem(mem)
    if shard_hub_console():
        try:
            from pallas.core.platform.shard.console_stats import load_cluster_console_stats_by_sid

            for sid, blob in load_cluster_console_stats_by_sid().items():
                key = str(sid).strip()
                if not key or (sid_f is not None and key != sid_f):
                    continue
                if not isinstance(blob, dict):
                    continue
                msg = blob.get("msg") if isinstance(blob.get("msg"), dict) else {}
                live_active[key] = live_active.get(key, set()) | _normalize_active_group_ids(
                    msg.get("day_active_groups")
                )
        except Exception:  # noqa: BLE001
            pass

    try:
        from packages.pb_webui import active_groups_store

        active_rows = active_groups_store.load_daily_active_counts(
            self_id=sid_f,
            start_day=start_d.isoformat(),
            end_day=end_d.isoformat(),
        )
        active_by_key = {(r["date"], r["self_id"]): int(r.get("active_groups") or 0) for r in active_rows}
        for row in merged:
            key = (str(row.get("date") or ""), str(row.get("self_id") or ""))
            count = active_by_key.get(key, 0)
            if key[0] == clock_today:
                live_ids = live_active.get(key[1], set())
                count = max(count, len(live_ids))
            row["active_groups"] = count
        group_metrics = active_groups_store.compute_group_metrics(
            self_id=sid_f,
            today=clock_today,
            mag_days=30,
            live_today=live_active,
        )
    except Exception:  # noqa: BLE001
        for row in merged:
            row.setdefault("active_groups", 0)
        group_metrics = {"dag": 0, "mag": 0, "dag_mag_ratio": None, "mag_days": 30}

    return {
        "start": s1,
        "end": s2,
        "query_start": start_d.isoformat(),
        "query_end": end_d.isoformat(),
        "rows": merged,
        "live_today": live_out,
        "server_date": clock_today,
        "group_metrics": group_metrics,
    }


async def _scheduled_refresh_plugin_update_snapshot() -> None:
    """每日 4:00 比对插件版本，刷新「有无新版本」快照。"""
    from pallas.console.webui.plugin_update_snapshot import refresh_plugin_update_snapshot

    try:
        await refresh_plugin_update_snapshot()
        drop_read_cache(("plugins-community-store", "plugins-official-extensions"))
    except Exception:  # noqa: BLE001
        logger.exception("Pallas-Bot 控制台: 定时刷新插件更新快照失败")


async def _scheduled_refresh_plugin_store_assets() -> None:
    from pallas.console.webui.plugin_store_assets import refresh_store_asset_snapshot

    try:
        await refresh_store_asset_snapshot()
        drop_read_cache(("plugins-community-store", "plugins-official-extensions"))
    except Exception:  # noqa: BLE001
        logger.exception("Pallas-Bot 控制台: 定时刷新插件商店资源快照失败")
