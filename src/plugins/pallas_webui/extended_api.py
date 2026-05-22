"""控制台扩展 JSON：系统/插件/连接/日志，以及实例、库、Bot/群配置等只读与受控写接口。"""

from __future__ import annotations

import asyncio
import contextvars
import copy
import json
import os
import platform
import shutil
import socket
import sys
import threading
import time
import traceback
import typing
from collections import defaultdict
from operator import itemgetter
from pathlib import Path
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from fastapi.responses import JSONResponse, StreamingResponse
from nonebot import get_bots, get_driver, logger
from nonebot.adapters import Bot as BaseBot  # noqa: TC002
from nonebot.adapters import Event  # noqa: TC002
from nonebot.matcher import Matcher  # noqa: TC002
from pydantic import BaseModel, ConfigDict, Field
from pydantic_core import PydanticUndefined

from src.common.web.bot_web import LogScope  # noqa: TC001  # FastAPI/OpenAPI 需在运行时解析注解
from src.common.webui import apply_plugin_config_patch, plugin_config_payload
from src.common.webui.console_login import (
    current_http_request,
    extract_session_from_request,
    is_console_auth_configured,
    mint_session_token,
    register_console_session_invalidation_hook,
    set_shared_console_login_token,
    verify_console_password,
)

from .api import _merge_console_version_from_disk

if typing.TYPE_CHECKING:
    from .config import Config

_CONSOLE_EXTRA: dict[str, Any] = {}
_INIT_LOG_SINK = False
_READ_CACHE: dict[str, dict[str, Any]] = {}


def clear_extended_read_cache() -> None:
    """清空控制台扩展 JSON 的进程内读缓存（口令轮换或新登录后调用）。"""
    _READ_CACHE.clear()


def _cache_value_copy(data: Any) -> Any:
    """避免调用方就地修改 dict/list 污染缓存条目。"""
    if isinstance(data, (dict, list)):
        try:
            return copy.deepcopy(data)
        except Exception:  # noqa: BLE001
            return data
    return data


_MSG_STATS: dict[str, dict[str, Any]] = {}  # self_id -> sent/received + 按本地日切片的 day_*
_MSG_TRACKING_INIT = False
# self_id -> 与 day_received / day_runs 等对齐的本地自然日（YYYY-MM-DD）；日切时落盘并清零当日字段
_CONSOLE_CAL_DAY: dict[str, str] = {}


def _parse_console_hist_params() -> tuple[int, int]:
    """协议 API / 消息吞吐 / Matcher 进程内时序桶（重启清空）。

    默认 1 分钟桶、最多 1440 桶（约 24 小时滑动窗口）。环境变量：
    - PALLAS_CONSOLE_HIST_BUCKET_SEC：桶宽（秒），建议能整除 86400（如 30、60、120、300）。
    - PALLAS_CONSOLE_HIST_MAX_BUCKETS：最多保留桶数；覆盖时长 ≈ 二者乘积。
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

    使用进程所在主机的本地时区、以当地自然日 00:00 起算的秒偏移对齐（非 Unix 纪元对齐）。
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
_WORKER_STATS_SYNC_STARTED = False
_WORKER_STATS_FAST_FLUSH_SEC = 3.0
_WORKER_STATS_HIST_FLUSH_SEC = 30.0
_EMPTY_MATCHER_HIST_SERIES: dict[str, list[Any]] = {
    "matcher_runs_by_plugin": [],
    "matcher_errors_by_plugin": [],
}
_EMPTY_MATCHER_DUR_HIST_SERIES: dict[str, list[Any]] = {
    "matcher_duration_ms_by_plugin": [],
    "matcher_avg_duration_ms_by_plugin": [],
}


def _is_console_stats_excluded_plugin(plugin: str) -> bool:
    from src.plugins.help.visibility import resolve_console_stats_excluded_plugin_names

    key = str(plugin or "").strip().lower()
    return bool(key) and key in resolve_console_stats_excluded_plugin_names()


_MATCHER_RUN_STARTED: contextvars.ContextVar[float | None] = contextvars.ContextVar(
    "matcher_run_started",
    default=None,
)
_MATCHER_ERROR_LOG_CAP = 80
_MATCHER_DURATION_LOG_CAP = 80
_MATCHER_ERROR_MSG_MAX = 2000
_MATCHER_ERROR_TB_MAX = 50_000
_MATCHER_ERROR_JSONL_LOCK = threading.Lock()
_MATCHER_DURATION_JSONL_LOCK = threading.Lock()
_LOG_ERROR_LOG_CAP = _MATCHER_ERROR_LOG_CAP
_LOG_ERROR_MSG_MAX = _MATCHER_ERROR_MSG_MAX
_LOG_ERROR_TB_MAX = _MATCHER_ERROR_TB_MAX
_LOG_ERROR_JSONL_LOCK = threading.Lock()
_LOG_ERROR_BUFFER: list[dict[str, Any]] = []


def set_console_meta(d: dict[str, Any] | None) -> None:
    """由 __init__ 在启动时注入 static_root、http_base 等，供 /system 与前端展示。"""
    _CONSOLE_EXTRA.clear()
    if d:
        _CONSOLE_EXTRA.update(d)


def _ensure_log_sink() -> None:
    global _INIT_LOG_SINK
    from src.common.web import install_nonebot_log_sink, set_log_error_capture

    install_nonebot_log_sink()
    set_log_error_capture(_append_log_error_from_sink)
    if _INIT_LOG_SINK:
        return
    _INIT_LOG_SINK = True
    logger.info("Pallas-Bot 控制台: 已接入 NoneBot 日志环（/pallas/api/logs）")


async def _cached_read(
    *,
    key: str,
    loader: typing.Callable[[], typing.Awaitable[Any]],
    ttl_sec: float = 1.0,
    stale_sec: float = 20.0,
) -> Any:
    """读取接口防抖：短 TTL 复用；失败时回退最近成功快照，降低前端空白概率。

    返回值对 dict/list 做拷贝，避免调用方修改污染缓存；口令轮换或新登录会清空整表。
    """
    now = time.monotonic()
    hit = _READ_CACHE.get(key)
    if hit and now < float(hit["exp"]):
        return _cache_value_copy(hit["data"])
    try:
        data = await loader()
    except Exception:
        if hit and now < float(hit["stale_exp"]):
            logger.warning("Pallas-Bot 控制台: 使用缓存兜底 key={}", key)
            return _cache_value_copy(hit["data"])
        raise
    stored = _cache_value_copy(data)
    _READ_CACHE[key] = {
        "data": stored,
        "exp": now + max(0.05, ttl_sec),
        "stale_exp": now + max(ttl_sec, stale_sec),
    }
    return _cache_value_copy(stored)


def _drop_read_cache(prefixes: tuple[str, ...]) -> None:
    if not _READ_CACHE:
        return
    for k in [k for k in _READ_CACHE if any(k.startswith(p) for p in prefixes)]:
        _READ_CACHE.pop(k, None)


# 审批写操作后：好友/群 OneBot 列表与按 Bot 群配置合并视图一并失效
_CONSOLE_APPROVAL_RELATED_CACHE_PREFIXES: tuple[str, ...] = (
    "friend_requests",
    "request_overview",
    "friend_list:",
    "group_list:",
    "group_configs_bot:",
)


def _metadata_to_dict(meta: object | None) -> dict[str, Any] | None:
    if meta is None:
        return None
    d: dict[str, Any] = {
        "name": getattr(meta, "name", None),
        "description": (getattr(meta, "description", None) or "")[:2000],
        "usage": (getattr(meta, "usage", None) or "")[:4000],
    }
    ex = getattr(meta, "extra", None)
    if ex:
        d["extra"] = dict(ex) if isinstance(ex, dict) else ex
    typ = getattr(meta, "type", None)
    if typ is not None:
        d["type"] = str(typ)
    return d


def _help_menu_control() -> tuple[set[str], set[str]]:
    """返回 (help 忽略名单, 额外隐藏名单)。"""
    ignored: set[str] = set()
    hidden: set[str] = set()
    try:
        from src.plugins.help.config import get_help_config
        from src.plugins.help.visibility import resolve_help_hidden_plugins

        cfg = get_help_config()
        ignored = {str(x).strip() for x in list(getattr(cfg, "ignored_plugins", []) or []) if str(x).strip()}
        hidden = {str(x).strip() for x in resolve_help_hidden_plugins() if str(x).strip()}
    except Exception:
        pass
    return ignored, hidden


def _list_plugins_dict() -> list[dict[str, Any]]:
    from src.common.webui.plugin_catalog import build_plugin_catalog_rows

    ignored, hidden = _help_menu_control()
    return build_plugin_catalog_rows(ignored=ignored, hidden=hidden)


def _jsonable_value(v: Any) -> Any:
    if v is PydanticUndefined:
        return None
    if isinstance(v, BaseModel):
        return v.model_dump(mode="python")
    if isinstance(v, Path):
        return str(v)
    if isinstance(v, dict):
        return {str(k): _jsonable_value(val) for k, val in v.items()}
    if isinstance(v, list):
        return [_jsonable_value(x) for x in v]
    if isinstance(v, (set, tuple)):
        return [_jsonable_value(x) for x in v]
    return v


_BOT_SESSION_CONNECTED_UNIX: dict[str, int] = {}
_BOT_SESSION_HOOKS_REGISTERED = False


def _ensure_bot_session_hooks() -> None:
    """进程内记录 Bot 接入时刻（连接时长展示）；WebUI 插件加载时注册一次。"""
    global _BOT_SESSION_HOOKS_REGISTERED
    if _BOT_SESSION_HOOKS_REGISTERED:
        return
    _BOT_SESSION_HOOKS_REGISTERED = True

    drv = get_driver()

    @drv.on_startup
    async def _prime_bot_session_times() -> None:
        try:
            for key in get_bots():
                _BOT_SESSION_CONNECTED_UNIX.setdefault(str(key), int(time.time()))
        except Exception:  # noqa: BLE001
            pass

    @drv.on_bot_connect
    async def _mark_bot_session(bot: BaseBot) -> None:
        try:
            for key, b in get_bots().items():
                if b is bot:
                    _BOT_SESSION_CONNECTED_UNIX[str(key)] = int(time.time())
                    return
            sid = getattr(bot, "self_id", None)
            if sid is None:
                return
            sids = str(sid)
            for key, b in get_bots().items():
                if str(getattr(b, "self_id", "")) == sids:
                    _BOT_SESSION_CONNECTED_UNIX[str(key)] = int(time.time())
                    return
        except Exception:  # noqa: BLE001
            pass


def _list_bots_dict() -> list[dict[str, Any]]:
    from src.common.bot_runtime.roles import is_sharded_hub
    from src.common.shard.registry.config import is_sharding_active

    if is_sharding_active() and is_sharded_hub():
        from src.common.shard.presence import list_connected_bots_for_webui

        return list_connected_bots_for_webui()

    rows: list[dict[str, Any]] = []
    for key, bot in get_bots().items():
        self_id: str
        try:
            self_id = str(bot.self_id)  # type: ignore[union-attr]
        except Exception:  # noqa: BLE001
            self_id = "?"
        adapter = ""
        try:
            a = bot.adapter
            if a is not None and hasattr(a, "get_name"):
                adapter = str(a.get_name())
        except Exception:  # noqa: BLE001
            pass
        rows.append({
            "connection_key": str(key),
            "self_id": self_id,
            "adapter": adapter,
            "connected_at_unix": _BOT_SESSION_CONNECTED_UNIX.get(str(key)),
        })
    return rows


def _bot_adapter_label(bot: object) -> str:
    try:
        a = getattr(bot, "adapter", None)
        if a is not None and hasattr(a, "get_name"):
            return str(a.get_name())
    except Exception:  # noqa: BLE001
        pass
    return ""


def _is_onebot_v11_bot(bot: object) -> bool:
    try:
        from nonebot.adapters.onebot.v11 import Bot as V11Bot  # type: ignore[attr-defined]

        return isinstance(bot, V11Bot)
    except Exception:  # noqa: BLE001
        return False


def _read_pending_friend_requests_disk() -> dict[str, dict[str, str]]:
    """与 request_handler 插件写入的 JSON 结构一致：{ bot_id: { user_id: flag } }。"""

    from src.common.paths import plugin_data_dir

    path = plugin_data_dir("request_handler", create=False) / "pending_friend_requests.json"
    if not path.exists():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}
    if not isinstance(raw, dict):
        return {}
    out: dict[str, dict[str, str]] = {}
    for bot_key, mp in raw.items():
        if not isinstance(mp, dict):
            continue
        bk = str(bot_key)
        out[bk] = {str(u): str(f) for u, f in mp.items()}
    return out


def _save_pending_friend_requests_disk(data: dict[str, dict[str, str]]) -> None:
    from src.common.paths import plugin_data_dir

    path = plugin_data_dir("request_handler") / "pending_friend_requests.json"
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _read_pending_group_requests_disk() -> dict[str, dict[str, dict[str, Any]]]:
    """与 request_handler 插件写入的 JSON 结构一致：{ bot_id: { group_id: request } }。"""

    from src.common.paths import plugin_data_dir

    path = plugin_data_dir("request_handler", create=False) / "pending_group_requests.json"
    if not path.exists():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}
    if not isinstance(raw, dict):
        return {}
    out: dict[str, dict[str, dict[str, Any]]] = {}
    for bot_key, mp in raw.items():
        if not isinstance(mp, dict):
            continue
        clean: dict[str, dict[str, Any]] = {}
        for req in mp.values():
            if not isinstance(req, dict):
                continue
            group_id = req.get("group_id")
            user_id = req.get("user_id")
            flag = req.get("flag")
            if flag is None:
                continue
            try:
                group_i = int(group_id)
                user_i = int(user_id)
            except (TypeError, ValueError):
                continue
            clean[str(group_i)] = {
                "flag": str(flag),
                "sub_type": str(req.get("sub_type") or "invite"),
                "user_id": user_i,
                "group_id": group_i,
                "comment": str(req.get("comment") or ""),
            }
        out[str(bot_key)] = clean
    return out


def _save_pending_group_requests_disk(data: dict[str, dict[str, dict[str, Any]]]) -> None:
    from src.common.paths import plugin_data_dir

    path = plugin_data_dir("request_handler") / "pending_group_requests.json"
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _ai_extension_config_path():
    from src.common.paths import plugin_data_dir

    return plugin_data_dir("pallas_webui") / "ai_extension.json"


def _ai_extension_log_roots() -> list[Path]:
    """允许的日志根目录：仓库根 + 同级 Pallas-Bot-AI 根。"""
    repo_root = Path(__file__).resolve().parents[3]
    ai_root = (repo_root.parent / "Pallas-Bot-AI").resolve()
    return [repo_root.resolve(), ai_root]


def _is_allowed_log_path(path_s: str) -> bool:
    """限制日志读取仅落在白名单根内，挡住 /etc/passwd 等任意文件读取。"""
    s = (path_s or "").strip()
    if not s:
        return False
    try:
        p = Path(s).resolve()
    except (OSError, RuntimeError):
        return False
    for root in _ai_extension_log_roots():
        try:
            if p == root or p.is_relative_to(root):
                return True
        except (OSError, RuntimeError):
            continue
    return False


def _normalize_ai_extension_config(raw: dict[str, Any] | None) -> dict[str, Any]:
    d = raw or {}
    base_url = str(d.get("base_url", "")).strip() or "http://127.0.0.1:9099"
    api_prefix = str(d.get("api_prefix", "")).strip() or "/api"
    if not api_prefix.startswith("/"):
        api_prefix = "/" + api_prefix
    token = str(d.get("token", "")).strip()
    health_paths_raw = d.get("health_paths", ["/health", "/api/health"])
    if isinstance(health_paths_raw, list):
        health_paths = [str(x).strip() for x in health_paths_raw if str(x).strip()]
    else:
        health_paths = ["/health", "/api/health"]
    if not health_paths:
        health_paths = ["/health", "/api/health"]
    root = Path(__file__).resolve().parents[3]
    default_ai_root = (root.parent / "Pallas-Bot-AI").resolve()
    default_uvicorn_log = str(default_ai_root / "logs" / "app.log")
    default_celery_log = str(default_ai_root / "logs" / "celery.log")
    uvicorn_log_file = str(d.get("uvicorn_log_file", "")).strip() or default_uvicorn_log
    celery_log_file = str(d.get("celery_log_file", "")).strip() or default_celery_log
    # 任一路径越界即回退默认值，避免被持票攻击者污染配置后读任意文件
    if not _is_allowed_log_path(uvicorn_log_file):
        uvicorn_log_file = default_uvicorn_log
    if not _is_allowed_log_path(celery_log_file):
        celery_log_file = default_celery_log
    timeout_sec = d.get("timeout_sec", 8)
    try:
        timeout_i = int(timeout_sec)
    except (TypeError, ValueError):
        timeout_i = 8
    timeout_i = max(2, min(timeout_i, 30))
    return {
        "base_url": base_url.rstrip("/"),
        "api_prefix": api_prefix,
        "token": token,
        "health_paths": health_paths,
        "uvicorn_log_file": uvicorn_log_file,
        "celery_log_file": celery_log_file,
        "timeout_sec": timeout_i,
    }


def _load_ai_extension_config() -> dict[str, Any]:
    path = _ai_extension_config_path()
    if not path.exists():
        return _normalize_ai_extension_config(None)
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return _normalize_ai_extension_config(None)
    if not isinstance(raw, dict):
        return _normalize_ai_extension_config(None)
    return _normalize_ai_extension_config(raw)


def _save_ai_extension_config(data: dict[str, Any]) -> dict[str, Any]:
    clean = _normalize_ai_extension_config(data)
    path = _ai_extension_config_path()
    path.write_text(json.dumps(clean, ensure_ascii=False, indent=2), encoding="utf-8")
    return clean


def _find_online_onebot_v11_bot(self_id: str) -> tuple[str, object]:
    target = str(self_id).strip()
    for key, bot in get_bots().items():
        if str(getattr(bot, "self_id", "") or "") != target:
            continue
        if not _is_onebot_v11_bot(bot):
            raise HTTPException(status_code=400, detail="当前连接不是 OneBot V11")
        return str(key), bot
    raise HTTPException(status_code=404, detail="指定账号当前未连接")


def _normalize_group_list_item(item: object) -> dict[str, Any] | None:
    if hasattr(item, "model_dump"):
        try:
            item = item.model_dump()  # type: ignore[union-attr]
        except Exception:  # noqa: BLE001
            pass
    elif hasattr(item, "dict") and callable(item.dict):
        try:
            item = item.dict()  # type: ignore[union-attr]
        except Exception:  # noqa: BLE001
            pass
    if not isinstance(item, dict):
        return None
    gid = item.get("group_id")
    try:
        group_id = int(gid)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    if group_id <= 0:
        return None
    try:
        member_count = int(float(item.get("member_count") or 0))
    except (TypeError, ValueError):
        member_count = 0
    try:
        max_member_count = int(float(item.get("max_member_count") or 0))
    except (TypeError, ValueError):
        max_member_count = 0
    return {
        "group_id": group_id,
        "group_name": str(item.get("group_name") or ""),
        "member_count": member_count,
        "max_member_count": max_member_count,
    }


def _normalize_friend_list_item(item: object) -> dict[str, Any] | None:
    if not isinstance(item, dict):
        return None
    uid = item.get("user_id")
    try:
        user_id = int(uid)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    if user_id <= 0:
        return None
    sex = item.get("sex")
    return {
        "user_id": user_id,
        "nickname": str(item.get("nickname") or ""),
        "remark": str(item.get("remark") or ""),
        **({"sex": sex} if sex is not None else {}),
    }


async def _call_get_group_list(
    bot: object,
    *,
    limit: int,
) -> tuple[list[dict[str, Any]], str | None, bool]:
    """OneBot V11 `get_group_list`；不同实现可能返回 list 或包在 dict 里。

    返回 (groups, error, truncated)。
    """
    try:
        raw = await bot.call_api("get_group_list")  # type: ignore[union-attr]
    except Exception as e:  # noqa: BLE001
        logger.warning("Pallas-Bot 控制台: get_group_list 调用失败: {}", e)
        return [], str(e), False
    groups_raw: list[Any]
    if isinstance(raw, list):
        groups_raw = raw
    elif isinstance(raw, dict):
        groups_raw = []
        for k in ("group_list", "groups", "data"):
            v = raw.get(k)
            if isinstance(v, list):
                groups_raw = v
                break
        if not groups_raw:
            logger.warning("Pallas-Bot 控制台: get_group_list 返回 dict 但未找到列表字段, keys={}", list(raw.keys()))
    else:
        logger.warning("Pallas-Bot 控制台: get_group_list 返回意外类型 {}", type(raw).__name__)
        groups_raw = []
    out: list[dict[str, Any]] = []
    for it in groups_raw:
        try:
            row = _normalize_group_list_item(it)
        except Exception as e:  # noqa: BLE001
            logger.warning("Pallas-Bot 控制台: 群列表条目解析失败 item={} err={}", repr(it), e)
            continue
        if row:
            out.append(row)
    out.sort(key=lambda r: int(r["group_id"]))
    truncated = len(out) > limit
    if truncated:
        out = out[:limit]
    return out, None, truncated


async def _call_get_friend_list(
    bot: object,
    *,
    limit: int,
) -> tuple[list[dict[str, Any]], str | None, bool]:
    """OneBot V11 `get_friend_list`；不同实现可能返回 list 或包在 dict 里。

    返回 (friends, error, truncated)。
    """
    try:
        raw = await bot.call_api("get_friend_list")  # type: ignore[union-attr]
    except Exception as e:  # noqa: BLE001
        return [], str(e), False
    friends_raw: list[Any]
    if isinstance(raw, list):
        friends_raw = raw
    elif isinstance(raw, dict):
        friends_raw = []
        for k in ("friend_list", "friends", "data"):
            v = raw.get(k)
            if isinstance(v, list):
                friends_raw = v
                break
    else:
        friends_raw = []
    out: list[dict[str, Any]] = []
    for it in friends_raw:
        row = _normalize_friend_list_item(it)
        if row:
            out.append(row)
    out.sort(key=lambda r: int(r["user_id"]))
    truncated = len(out) > limit
    if truncated:
        out = out[:limit]
    return out, None, truncated


def _rows_from_doubt_friends_api(raw: object) -> list[dict[str, Any]]:
    if isinstance(raw, list):
        return [x for x in raw if isinstance(x, dict)]
    if isinstance(raw, dict):
        data = raw.get("data")
        if isinstance(data, list):
            return [x for x in data if isinstance(x, dict)]
    return []


async def _call_get_doubt_friends(bot: object) -> list[dict[str, Any]]:
    try:
        raw = await bot.call_api("get_doubt_friends_add_request", count=50)  # type: ignore[union-attr]
    except Exception:  # noqa: BLE001
        return []
    rows = _rows_from_doubt_friends_api(raw)
    out: list[dict[str, Any]] = []
    for x in rows:
        uid_raw = x.get("user_id")
        if uid_raw is None:
            uid_raw = x.get("uin")
        if uid_raw is None:
            continue
        try:
            uid = int(uid_raw)
        except (TypeError, ValueError):
            continue
        flag = x.get("flag")
        if flag is None:
            continue
        flag_str = str(flag).strip()
        if not flag_str:
            continue
        row: dict[str, Any] = {"user_id": uid, "flag": flag_str}
        nick_raw = x.get("nickname") or x.get("nick") or x.get("name")
        if isinstance(nick_raw, str) and nick_raw.strip():
            row["nickname"] = nick_raw.strip()
        out.append(row)
    return out


async def _call_get_stranger_info_raw(bot: object, user_id: int) -> dict[str, Any] | None:
    try:
        raw = await bot.call_api("get_stranger_info", user_id=user_id)  # type: ignore[union-attr]
    except Exception:  # noqa: BLE001
        return None
    return raw if isinstance(raw, dict) else None


def _nickname_from_stranger_info(raw: dict[str, Any]) -> str:
    nick = raw.get("nickname")
    if isinstance(nick, str) and nick.strip():
        return nick.strip()
    data = raw.get("data")
    if isinstance(data, dict):
        nick2 = data.get("nickname")
        if isinstance(nick2, str) and nick2.strip():
            return nick2.strip()
    return ""


async def _enrich_friend_request_rows_nicknames(
    bot: object,
    pending: list[dict[str, Any]],
    doubt: list[dict[str, Any]],
) -> None:
    if not _is_onebot_v11_bot(bot):
        return
    need: set[int] = set()
    for p in pending:
        if str(p.get("nickname", "")).strip():
            continue
        uid = p.get("user_id")
        if uid is None:
            continue
        try:
            need.add(int(uid))
        except (TypeError, ValueError):
            pass
    for d in doubt:
        if str(d.get("nickname", "")).strip():
            continue
        uid = d.get("user_id")
        if uid is None:
            continue
        try:
            need.add(int(uid))
        except (TypeError, ValueError):
            pass
    nick_map: dict[int, str] = {}
    for uid in sorted(need):
        raw = await _call_get_stranger_info_raw(bot, uid)
        if raw is None:
            continue
        nick = _nickname_from_stranger_info(raw)
        if nick:
            nick_map[uid] = nick
    for p in pending:
        try:
            uid = int(p["user_id"])
        except (KeyError, TypeError, ValueError):
            continue
        if str(p.get("nickname", "")).strip():
            continue
        if uid in nick_map:
            p["nickname"] = nick_map[uid]
    for d in doubt:
        try:
            uid = int(d["user_id"])
        except (KeyError, TypeError, ValueError):
            continue
        if str(d.get("nickname", "")).strip():
            continue
        if uid in nick_map:
            d["nickname"] = nick_map[uid]


def _normalize_message_item(item: object) -> dict[str, Any] | None:
    if not isinstance(item, dict):
        return None
    out: dict[str, Any] = {}
    for k in ("message_id", "time", "raw_message", "message_type"):
        v = item.get(k)
        if v is not None:
            out[k] = v
    sender = item.get("sender")
    if isinstance(sender, dict):
        nick = sender.get("nickname")
        if nick is not None:
            out["nickname"] = str(nick)
        uid = sender.get("user_id")
        if uid is not None:
            try:
                out["user_id"] = int(uid)
            except (TypeError, ValueError):
                pass
    uid2 = item.get("user_id")
    if "user_id" not in out and uid2 is not None:
        try:
            out["user_id"] = int(uid2)
        except (TypeError, ValueError):
            pass
    gid = item.get("group_id")
    if gid is not None:
        try:
            out["group_id"] = int(gid)
        except (TypeError, ValueError):
            pass
    if not out:
        return None
    return out


def _gpu_metrics() -> dict[str, Any]:
    """GPU 监控（可选）：优先 NVML，未安装时返回 unavailable。"""
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


def _rollover_console_day_if_needed(sid: str, today: str) -> None:
    """跨自然日时把上一日的消息收/发与 Matcher 当日计数写入磁盘并清零当日字段。"""
    from src.plugins.pallas_webui import daily_stats_store

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
    mr = _sum_matcher_day_runs(sid)
    daily_stats_store.write_day_totals(cur, sid, dr, ds, mr)
    if isinstance(mem, dict):
        mem["day_key"] = today
        mem["day_sent"] = 0
        mem["day_received"] = 0
        mem["day_api_total"] = 0
        mem["day_api_counts"] = {}
    pblock = _PLUGIN_RUN_STATS.get(sid)
    if isinstance(pblock, dict):
        pblock["day_key"] = today
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
    """定时刷盘：当前自然日内累计值写入磁盘（不按桶）。"""
    from src.plugins.pallas_webui import daily_stats_store

    today = time.strftime("%Y-%m-%d", time.localtime())
    sids = set(_MSG_STATS.keys()) | set(_PLUGIN_RUN_STATS.keys()) | set(_CONSOLE_CAL_DAY.keys())
    for sid in sids:
        sid = str(sid).strip()
        if not sid:
            continue
        _rollover_console_day_if_needed(sid, today)
        mem = _MSG_STATS.get(sid)
        dr = int(mem.get("day_received", 0)) if isinstance(mem, dict) else 0
        ds = int(mem.get("day_sent", 0)) if isinstance(mem, dict) else 0
        mr = _sum_matcher_day_runs(sid)
        daily_stats_store.write_day_totals(today, sid, dr, ds, mr)


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
        msg = {
            "sent": int(mem.get("sent", 0)),
            "received": int(mem.get("received", 0)),
            "day_sent": int(mem.get("day_sent", 0)),
            "day_received": int(mem.get("day_received", 0)),
            "day_key": str(mem.get("day_key") or ""),
        }
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


def flush_worker_shard_console_stats_sync(*, include_hist: bool = False) -> None:
    from src.common.bot_runtime.roles import is_sharded_worker
    from src.common.shard.console_stats import write_worker_stats_sync
    from src.common.shard.registry.config import get_shard_registry_settings

    if not is_sharded_worker():
        return
    shard_id = int(get_shard_registry_settings().shard_id)
    write_worker_stats_sync(
        shard_id=shard_id,
        bots=_collect_worker_console_stats_snapshot(include_hist=include_hist),
        preserve_matcher_hist=not include_hist,
    )


def _restore_worker_console_stats_from_shard_file() -> None:
    from src.common.bot_runtime.roles import is_sharded_worker
    from src.common.shard.console_stats import load_worker_console_stats_for_boot
    from src.common.shard.registry.config import get_shard_registry_settings

    if not is_sharded_worker():
        return
    shard_id = int(get_shard_registry_settings().shard_id)
    bots = load_worker_console_stats_for_boot(shard_id)
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
            _MSG_STATS[sid] = {
                "sent": int(msg.get("sent", 0)),
                "received": int(msg.get("received", 0)),
                "day_sent": int(msg.get("day_sent", 0)),
                "day_received": int(msg.get("day_received", 0)),
                "day_key": str(msg.get("day_key") or today),
                "day_api_total": 0,
                "day_api_counts": {},
                "api_call_buckets": [],
                "msg_traffic_buckets": [],
            }
        _CONSOLE_CAL_DAY[sid] = str(bucket.get("day_key") or today)


def start_worker_shard_console_stats_sync() -> None:
    global _WORKER_STATS_SYNC_STARTED
    if _WORKER_STATS_SYNC_STARTED:
        return
    from src.common.bot_runtime.roles import is_sharded_worker

    if not is_sharded_worker():
        return
    _WORKER_STATS_SYNC_STARTED = True

    async def _fast_loop() -> None:
        while True:
            try:
                flush_worker_shard_console_stats_sync(include_hist=False)
                _flush_today_console_daily_stats_disk()
            except Exception:  # noqa: BLE001
                pass
            await asyncio.sleep(_WORKER_STATS_FAST_FLUSH_SEC)

    async def _hist_loop() -> None:
        while True:
            try:
                flush_worker_shard_console_stats_sync(include_hist=True)
            except Exception:  # noqa: BLE001
                pass
            await asyncio.sleep(_WORKER_STATS_HIST_FLUSH_SEC)

    asyncio.create_task(_fast_loop())
    asyncio.create_task(_hist_loop())


def ensure_console_metrics_hooks() -> None:
    """单进程 / hub WebUI 与分片 worker（pallas_console_metrics）共用。"""
    _ensure_bot_session_hooks()
    _init_message_tracking()
    _init_plugin_run_tracking()


def _msg_stats_get_mut(sid: str) -> dict[str, Any]:
    """返回可写的内存统计行；跨本地自然日时清零当日计数（与 Matcher 日计数统一落盘）。"""
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
    return rec


_HIST_API_SERIES_MAX = 24
_HIST_PLUGIN_SERIES_MAX = 20


def _api_call_history_bump(row: dict[str, Any], api: str) -> None:
    """按时间桶记录各接口成功调用次数（与 day_api_total 口径一致；桶按主机本地 wall-clock 对齐）。"""
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
    """按与协议 API 相同的时间桶记录消息收/发条数（进程内，重启丢失；桶按主机本地 wall-clock 对齐）。"""
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
    """注册 NoneBot2 钩子：消息收/发；协议 API 今日计数与按时间桶（见 _API_HIST_BUCKET_SEC）；消息收/发时间桶。"""
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
    return {
        "sent": int(msg.get("sent", 0)),
        "received": int(msg.get("received", 0)),
        "day_sent": int(msg.get("day_sent", 0)),
        "day_received": int(msg.get("day_received", 0)),
        "day_key": str(msg.get("day_key") or ""),
        "day_api_total": 0,
        "day_api_counts": {},
        "api_call_buckets": [],
        "msg_traffic_buckets": [],
    }


async def _message_stats_overview(*, self_id: str | None) -> dict[str, Any]:
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

    from src.common.bot_runtime.roles import is_sharded_hub
    from src.common.shard.registry.config import is_sharding_active

    if is_sharding_active() and is_sharded_hub():
        from src.common.shard.console_stats import load_cluster_console_stats_by_sid
        from src.common.shard.presence import read_presence_bots

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


def _avg_duration_ms(ms_sum: int, count: int) -> int | None:
    if count <= 0:
        return None
    return int(round(int(ms_sum) / int(count)))


def _matcher_elapsed_ms(started: float | None) -> float:
    """Matcher 墙钟耗时（毫秒，保留两位小数；极短执行可能为 0.0）。"""
    if started is None:
        return 0.0
    return max(0.0, round((time.perf_counter() - started) * 1000, 2))


def _record_plugin_run_duration(sid: str, plugin: str, elapsed_ms: int | float) -> None:
    ms = max(0, int(round(float(elapsed_ms))))
    row = _plugin_run_plugin_row(sid, plugin)
    row["duration_ms_sum"] = int(row["duration_ms_sum"]) + ms
    row["duration_count"] = int(row["duration_count"]) + 1
    row["duration_ms_max"] = max(int(row["duration_ms_max"]), ms)
    row["day_duration_ms_sum"] = int(row["day_duration_ms_sum"]) + ms
    row["day_duration_count"] = int(row["day_duration_count"]) + 1
    row["day_duration_ms_max"] = max(int(row["day_duration_ms_max"]), ms)


def _append_matcher_error_log(sid: str, plugin: str, exception: BaseException) -> None:
    """进程内环形缓冲 + jsonl；与定时清理共用锁，避免与每日清空交错。"""
    from src.common.paths import plugin_data_dir

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
        path = plugin_data_dir("pallas_webui") / "matcher_errors.jsonl"
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
    """用各账号进程内缓冲（每账号最多 _MATCHER_DURATION_LOG_CAP 条）覆写 jsonl。"""
    from src.common.paths import plugin_data_dir

    path = plugin_data_dir("pallas_webui") / "matcher_durations.jsonl"
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
                "duration_ms": max(0.0, round(float(it.get("duration_ms") or 0), 2)),
                "had_error": bool(it.get("had_error")),
            }
            lines.append(json.dumps(line_obj, ensure_ascii=False))
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".jsonl.tmp")
    tmp.write_text(("\n".join(lines) + ("\n" if lines else "")), encoding="utf-8")
    tmp.replace(path)


def _load_matcher_duration_logs_from_disk() -> None:
    """启动时从 jsonl 恢复各账号最近 _MATCHER_DURATION_LOG_CAP 条单次耗时。"""
    from src.common.paths import plugin_data_dir

    path = plugin_data_dir("pallas_webui") / "matcher_durations.jsonl"
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
            duration_ms = max(0.0, round(float(obj.get("duration_ms") or 0), 2))
        except (TypeError, ValueError):
            duration_ms = 0.0
        by_sid[sid].append({
            "at": at,
            "plugin": str(obj.get("plugin") or ""),
            "duration_ms": duration_ms,
            "had_error": bool(obj.get("had_error")),
        })
    cap = _MATCHER_DURATION_LOG_CAP
    for sid, entries in by_sid.items():
        rec = _plugin_run_bot_bucket(sid)
        rec["matcher_duration_log"] = entries[-cap:]


def _append_matcher_duration_log(
    sid: str,
    plugin: str,
    duration_ms: int | float,
    *,
    had_error: bool,
) -> None:
    """进程内环形缓冲；单进程/hub 另写 jsonl；分片 worker 由 stats 文件周期刷盘。"""
    from src.common.bot_runtime.roles import is_sharded_worker

    entry: dict[str, Any] = {
        "at": int(time.time()),
        "plugin": plugin,
        "duration_ms": max(0.0, round(float(duration_ms), 2)),
        "had_error": bool(had_error),
    }
    try:
        rec = _plugin_run_bot_bucket(sid)
        log = rec.setdefault("matcher_duration_log", [])
        if not isinstance(log, list):
            rec["matcher_duration_log"] = []
            log = rec["matcher_duration_log"]
        log.append(entry)
        while len(log) > _MATCHER_DURATION_LOG_CAP:
            log.pop(0)
        if is_sharded_worker():
            return
        with _MATCHER_DURATION_JSONL_LOCK:
            _rewrite_matcher_durations_jsonl()
    except Exception:  # noqa: BLE001
        pass


def _matcher_duration_log_public(
    rec: dict[str, Any],
    *,
    limit: int = _MATCHER_DURATION_LOG_CAP,
) -> list[dict[str, Any]]:
    raw = rec.get("matcher_duration_log")
    if not isinstance(raw, list) or not raw:
        return []
    out: list[dict[str, Any]] = []
    for it in reversed(raw[-limit:]):
        if not isinstance(it, dict):
            continue
        try:
            at = int(it.get("at") or 0)
        except (TypeError, ValueError):
            at = 0
        try:
            duration_ms = max(0.0, round(float(it.get("duration_ms") or 0), 2))
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
    """从 loguru record 取 (exc_type, message, traceback 文本)。"""
    try:
        msg = str(record["message"])
    except Exception:  # noqa: BLE001
        msg = ""
    exc_type = "LogError"
    tb = ""
    try:
        ex = record["exception"]
    except Exception:  # noqa: BLE001
        return exc_type, msg, tb
    if not ex:
        return exc_type, msg, tb
    et = val = tb_obj = None
    try:
        if hasattr(ex, "type"):
            et = ex.type
            val = getattr(ex, "value", None)
            tb_obj = getattr(ex, "traceback", None)
        elif isinstance(ex, tuple) and len(ex) >= 3:
            et, val, tb_obj = ex[0], ex[1], ex[2]
    except Exception:  # noqa: BLE001
        return exc_type, msg, tb
    if val is not None:
        exc_type = type(val).__name__
    elif et is not None:
        exc_type = getattr(et, "__name__", str(et))
    try:
        tb = "".join(traceback.format_exception(et, val, tb_obj))
    except Exception:  # noqa: BLE001
        tb = str(val) if val is not None else ""
    return exc_type, msg, tb


def _append_console_log_error(entry: dict[str, Any]) -> None:
    from src.common.paths import plugin_data_dir

    path = plugin_data_dir("pallas_webui") / "log_errors.jsonl"
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
    exc_type, msg, tb = _tb_and_exc_type_from_log_record(record)
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
        from src.common.bot_runtime.roles import is_sharded_hub

        if is_sharded_hub():
            from src.common.shard.logs.errors import append_shard_log_error, log_stem_for_shard
            from src.common.shard.registry.config import get_shard_registry_settings

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
        from src.common.bot_runtime.roles import is_sharded_hub

        if is_sharded_hub():
            sharded = True
            from src.common.shard.logs.view import list_shard_log_sources

            sources = list_shard_log_sources()
    except Exception:
        pass
    return {"sharded_log_errors": sharded, "log_error_sources": sources}


def _log_error_log_public(
    *,
    limit: int = 30,
    tb_limit: int = 0,
    source: str | None = None,
) -> list[dict[str, Any]]:
    with _LOG_ERROR_JSONL_LOCK:
        raw = list(_LOG_ERROR_BUFFER)
    merged: list[dict[str, Any]] = [dict(it) for it in raw if isinstance(it, dict)]
    try:
        from src.common.bot_runtime.roles import is_sharded_hub

        if is_sharded_hub():
            from src.common.shard.logs.view import collect_cluster_log_errors

            merged.extend(collect_cluster_log_errors(per_file=800, limit=max(limit * 4, 80)))
    except Exception:
        pass
    if not merged:
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
    return bucket[-limit:]


def _cleanup_log_error_archives_sync() -> None:
    from src.common.paths import plugin_data_dir

    path = plugin_data_dir("pallas_webui") / "log_errors.jsonl"
    with _LOG_ERROR_JSONL_LOCK:
        try:
            if path.exists():
                path.unlink()
        except OSError as e:
            logger.warning("Pallas-Bot 控制台: 删除 log_errors.jsonl 失败: {}", str(e))
        _LOG_ERROR_BUFFER.clear()


async def _scheduled_cleanup_matcher_error_logs() -> None:
    """每日 4:00 清理 Matcher 异常与日志 ERROR 归档（jsonl + 进程内缓冲）。"""
    from src.common.paths import plugin_data_dir

    err_path = plugin_data_dir("pallas_webui") / "matcher_errors.jsonl"
    dur_path = plugin_data_dir("pallas_webui") / "matcher_durations.jsonl"
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
        from src.common.bot_runtime.roles import is_sharded_hub

        if is_sharded_hub():
            from src.common.shard.console_stats import iter_worker_shard_ids, trim_worker_duration_logs_sync
            from src.common.shard.logs.errors import cleanup_shard_error_archives_sync

            cleanup_shard_error_archives_sync()
            from src.common.shard.logs.view import cleanup_stale_shard_log_files

            cleanup_stale_shard_log_files()
            for wid in iter_worker_shard_ids():
                trim_worker_duration_logs_sync(shard_id=wid, cap=0)
    except Exception:
        pass
    _drop_read_cache(("plugin-run-stats:",))
    logger.info(
        "Pallas-Bot 控制台: 控制台异常记录已按计划清理（每日 4:00，"
        "matcher_errors.jsonl、matcher_durations.jsonl、log_errors.jsonl、分片 errors/*.jsonl 与进程内缓冲）"
    )


def _matcher_hist_bump(sid: str, plugin: str, had_error: bool, *, duration_ms: int = 0) -> None:
    """Matcher 执行按时间桶、按插件名记录（与 plugin-run-stats 插件维度一致）。"""
    pname = str(plugin).strip() or "_"
    dur = max(0, int(duration_ms))
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
            if dur > 0:
                durs = hist[-1].setdefault("plugin_duration_ms", {})
                if not isinstance(durs, dict):
                    hist[-1]["plugin_duration_ms"] = {}
                    durs = hist[-1]["plugin_duration_ms"]
                durs[pname] = int(durs.get(pname, 0)) + dur
            if had_error:
                errs = hist[-1].setdefault("plugin_errors", {})
                if not isinstance(errs, dict):
                    hist[-1]["plugin_errors"] = {}
                    errs = hist[-1]["plugin_errors"]
                errs[pname] = int(errs.get(pname, 0)) + 1
            return
    entry: dict[str, Any] = {"at": bucket, "plugins": {pname: 1}}
    if dur > 0:
        entry["plugin_duration_ms"] = {pname: dur}
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
    """各插件 Matcher 耗时（毫秒）按时间桶累计；与 matcher_runs 同桶可算平均耗时。"""
    raw = rec.get("matcher_hist")
    ranked: list[str] = []
    by_plugin = rec.get("by_plugin")
    if isinstance(by_plugin, dict) and by_plugin:

        def _day_dur_sum(plugin_key: str) -> int:
            prow = by_plugin.get(plugin_key)
            if not isinstance(prow, dict):
                return 0
            return int(prow.get("day_duration_ms_sum", 0))

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
            ms = 0
            if isinstance(durs, dict):
                try:
                    ms = int(durs.get(pname, 0))
                except (TypeError, ValueError):
                    ms = 0
            if ms <= 0 and runs <= 0:
                continue
            ms_pts.append({"at": at, "total": ms})
            if runs > 0 and ms > 0:
                avg_pts.append({"at": at, "total": int(round(ms / runs))})
        if sum(int(x.get("total", 0) or 0) for x in ms_pts):
            ms_out.append({"plugin": pname, "points": ms_pts})
        if sum(int(x.get("total", 0) or 0) for x in avg_pts):
            avg_out.append({"plugin": pname, "points": avg_pts})
    return {
        "matcher_duration_ms_by_plugin": ms_out,
        "matcher_avg_duration_ms_by_plugin": avg_out,
    }


def _init_plugin_run_tracking() -> None:
    """run_pre/postprocessor：Matcher 墙钟耗时与次数（不含被 run_preprocessor 拦截的调度）。"""
    global _PLUGIN_RUN_TRACKING_INIT
    if _PLUGIN_RUN_TRACKING_INIT:
        return
    _PLUGIN_RUN_TRACKING_INIT = True
    from src.common.bot_runtime.roles import is_sharded_worker

    if is_sharded_worker():
        _restore_worker_console_stats_from_shard_file()
    else:
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
        _MATCHER_RUN_STARTED.set(time.perf_counter())

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
        started = _MATCHER_RUN_STARTED.get()
        elapsed_ms = _matcher_elapsed_ms(started)
        try:
            row = _plugin_run_plugin_row(sid, plugin)
            row["runs"] = int(row["runs"]) + 1
            row["day_runs"] = int(row["day_runs"]) + 1
            if exception is not None:
                row["errors"] = int(row["errors"]) + 1
                row["day_errors"] = int(row["day_errors"]) + 1
                _append_matcher_error_log(sid, plugin, exception)
            if elapsed_ms > 0:
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
                duration_ms=int(round(elapsed_ms)),
            )
        except Exception:  # noqa: BLE001
            pass
        finally:
            _MATCHER_RUN_STARTED.set(None)


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
        dsum = int(prow.get("duration_ms_sum", 0))
        dcnt = int(prow.get("duration_count", 0))
        dmax = int(prow.get("duration_ms_max", 0))
        dsum_t = int(prow.get("day_duration_ms_sum", 0))
        dcnt_t = int(prow.get("day_duration_count", 0))
        dmax_t = int(prow.get("day_duration_ms_max", 0))
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
    }


def _plugin_run_stats_overview(
    *,
    self_id: str | None,
    log_source: str | None = None,
    tb_limit: int = 0,
) -> dict[str, Any]:
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

    from src.common.bot_runtime.roles import is_sharded_hub
    from src.common.shard.registry.config import is_sharding_active

    if is_sharding_active() and is_sharded_hub():
        from src.common.shard.console_stats import load_cluster_console_stats_by_sid
        from src.common.shard.presence import read_presence_bots

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
    return {
        "total_runs": total_runs,
        "total_errors": total_errors,
        "total_runs_today": total_runs_today,
        "total_errors_today": total_errors_today,
        "matcher_calls_history_bucket_sec": _API_HIST_BUCKET_SEC,
        "matcher_calls_history_max_buckets": _API_HIST_MAX_BUCKETS,
        "log_error_log": _log_error_log_public(source=log_source, tb_limit=tb_limit),
        "bots": rows_out,
        **_log_error_log_meta(),
    }


def _console_daily_stats_payload(
    *,
    self_id: str | None,
    start: str | None,
    end: str | None,
) -> dict[str, Any]:
    """按自然日汇总：消息收/发与 Matcher 次数（磁盘 + 当前日内存）。"""
    from datetime import date, timedelta

    from src.plugins.pallas_webui import daily_stats_store

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
    from src.common.bot_runtime.roles import is_sharded_hub
    from src.common.shard.registry.config import is_sharding_active

    if is_sharding_active() and is_sharded_hub():
        from src.common.shard.console_stats import load_cluster_console_stats_by_sid

        for sid, blob in load_cluster_console_stats_by_sid().items():
            sid = str(sid).strip()
            if not sid or (sid_f is not None and sid != sid_f):
                continue
            msg = blob.get("msg") if isinstance(blob, dict) else {}
            dr = int(msg.get("day_received", 0)) if isinstance(msg, dict) else 0
            ds = int(msg.get("day_sent", 0)) if isinstance(msg, dict) else 0
            mr = 0
            bp = blob.get("by_plugin") if isinstance(blob, dict) else {}
            if isinstance(bp, dict):
                for prow in bp.values():
                    if isinstance(prow, dict):
                        mr += int(prow.get("day_runs", 0))
            live_out[sid] = {"received": dr, "sent": ds, "matcher_runs": mr}
            if start_d <= today_d <= end_d:
                k = (clock_today, sid)
                if k in by_key:
                    by_key[k]["received"] = dr
                    by_key[k]["sent"] = ds
                    by_key[k]["matcher_runs"] = mr
                else:
                    by_key[k] = {
                        "date": clock_today,
                        "self_id": sid,
                        "received": dr,
                        "sent": ds,
                        "matcher_runs": mr,
                    }
    for sid in set(_MSG_STATS.keys()) | set(_PLUGIN_RUN_STATS.keys()):
        sid = str(sid).strip()
        if not sid:
            continue
        if sid_f is not None and sid != sid_f:
            continue
        _rollover_console_day_if_needed(sid, clock_today)
        mem = _MSG_STATS.get(sid)
        dr = int(mem.get("day_received", 0)) if isinstance(mem, dict) else 0
        ds = int(mem.get("day_sent", 0)) if isinstance(mem, dict) else 0
        mr = _sum_matcher_day_runs(sid)
        live_out[sid] = {"received": dr, "sent": ds, "matcher_runs": mr}
        if start_d <= today_d <= end_d:
            k = (clock_today, sid)
            if k in by_key:
                by_key[k]["received"] = dr
                by_key[k]["sent"] = ds
                by_key[k]["matcher_runs"] = mr
            else:
                by_key[k] = {
                    "date": clock_today,
                    "self_id": sid,
                    "received": dr,
                    "sent": ds,
                    "matcher_runs": mr,
                }
    merged = sorted(by_key.values(), key=itemgetter("date", "self_id"))
    return {
        "start": s1,
        "end": s2,
        "query_start": start_d.isoformat(),
        "query_end": end_d.isoformat(),
        "rows": merged,
        "live_today": live_out,
        "server_date": clock_today,
    }


async def _call_get_message_history(
    bot: object,
    *,
    kind: Literal["friend", "group"],
    target_id: int,
    count: int,
) -> list[dict[str, Any]]:
    base_params: dict[str, Any] = {
        "count": int(count),
        "reverse_order": False,
        "disable_get_url": False,
        "parse_mult_msg": True,
        "quick_reply": False,
        "reverseOrder": False,
    }
    if kind == "friend":
        key = "user_id"
        api_name = "get_friend_msg_history"
    else:
        key = "group_id"
        api_name = "get_group_msg_history"
    target_num = int(target_id)
    tried: list[dict[str, Any]] = [
        {**base_params, key: target_num},
        {**base_params, key: str(target_num)},
        {"count": int(count), key: target_num},
        {"count": int(count), key: str(target_num)},
    ]
    last_err: Exception | None = None
    raw: Any = {}
    for params in tried:
        try:
            raw = await bot.call_api(api_name, **params)  # type: ignore[union-attr]
            last_err = None
            break
        except Exception as e:  # noqa: BLE001
            last_err = e
    if last_err is not None:
        raise last_err
    messages_raw: list[Any] = []
    if isinstance(raw, dict):
        maybe = raw.get("messages")
        if isinstance(maybe, list):
            messages_raw = maybe
        elif isinstance(raw.get("data"), dict):
            inner = raw["data"].get("messages")
            if isinstance(inner, list):
                messages_raw = inner
    elif isinstance(raw, list):
        messages_raw = raw
    out: list[dict[str, Any]] = []
    for it in messages_raw:
        row = _normalize_message_item(it)
        if row:
            out.append(row)
    out.sort(key=lambda x: int(x.get("time") or 0))
    return out


async def _collect_online_bot_profiles() -> dict[str, dict[str, Any]]:
    """尽力读取在线 OneBot V11 账号资料，失败时忽略单个账号并保留其它结果。"""
    from src.common.bot_runtime.roles import is_sharded_hub
    from src.common.shard.registry.config import is_sharding_active

    if is_sharding_active() and is_sharded_hub():
        from src.common.shard.presence import read_presence_bots
        from src.common.webui.protocol_accounts import protocol_account_display_names

        names = protocol_account_display_names()
        out: dict[str, dict[str, Any]] = {}
        for qq, rec in read_presence_bots().items():
            sid = str(rec.get("qq") or qq)
            nick = str(rec.get("nickname") or "").strip() or names.get(sid, "")
            out[sid] = {
                "nickname": nick,
                "user_id": int(sid) if sid.isdigit() else None,
                "connection_key": str(rec.get("connection_key") or sid),
                "adapter": str(rec.get("adapter") or ""),
                "shard_id": rec.get("shard_id"),
            }
        from src.common.db.pallas_console_data import pallas_protocol_snapshot

        snap = pallas_protocol_snapshot()
        if snap and isinstance(snap.get("accounts"), list):
            for acc in snap["accounts"]:
                if not isinstance(acc, dict):
                    continue
                sid = str(acc.get("qq") or acc.get("id") or "").strip()
                if not sid.isdigit():
                    continue
                disp = str(acc.get("display_name") or "").strip()
                if sid in out:
                    if disp and not out[sid].get("nickname"):
                        out[sid]["nickname"] = disp
                elif disp:
                    out[sid] = {
                        "nickname": disp,
                        "user_id": int(sid),
                        "connection_key": sid,
                        "adapter": "",
                        "shard_id": None,
                        "online": False,
                    }
        return out

    out: dict[str, dict[str, Any]] = {}
    for key, bot in get_bots().items():
        self_id = str(getattr(bot, "self_id", "") or "").strip()
        if not self_id:
            continue
        if not _is_onebot_v11_bot(bot):
            continue
        try:
            raw = await bot.call_api("get_login_info")  # type: ignore[union-attr]
        except Exception:  # noqa: BLE001
            logger.debug("Pallas-Bot 控制台: get_login_info 失败 key={} self_id={}", key, self_id)
            continue
        if not isinstance(raw, dict):
            continue
        nickname = str(raw.get("nickname") or "").strip()
        user_id = raw.get("user_id")
        out[self_id] = {
            "nickname": nickname,
            "user_id": int(user_id) if isinstance(user_id, int) else None,
            "connection_key": str(key),
            "adapter": _bot_adapter_label(bot),
        }
    return out


async def _friend_requests_overview(
    *,
    self_id: str | None,
    include_doubt: bool,
) -> dict[str, Any]:
    disk = _read_pending_friend_requests_disk()
    online_by_self: dict[str, tuple[str, object]] = {}
    from src.common.bot_runtime.roles import is_sharded_hub
    from src.common.shard.registry.config import is_sharding_active

    if is_sharding_active() and is_sharded_hub():
        from src.common.shard.presence import read_presence_bots

        for key, rec in read_presence_bots().items():
            sid = str(rec.get("qq") or key)
            if sid:
                online_by_self[sid] = (str(rec.get("connection_key") or sid), None)
    else:
        for key, bot in get_bots().items():
            sid = str(getattr(bot, "self_id", "") or "")
            if sid:
                online_by_self[sid] = (str(key), bot)

    ids = set(disk.keys()) | set(online_by_self.keys())
    if self_id is not None and str(self_id).strip():
        want = str(self_id).strip()
        ids = {i for i in ids if i == want}

    def _sort_key(s: str) -> tuple[int, str]:
        return (int(s), s) if s.isdigit() else (10**18, s)

    rows: list[dict[str, Any]] = []
    for sid in sorted(ids, key=_sort_key):
        pend_map = disk.get(sid, {})
        pending = [{"user_id": int(u), "flag": fl} for u, fl in pend_map.items() if u.isdigit()]
        doubt: list[dict[str, Any]] = []
        conn: str | None = None
        adapter = ""
        online = sid in online_by_self
        if online:
            conn, bot = online_by_self[sid]
            adapter = _bot_adapter_label(bot)
            if include_doubt and _is_onebot_v11_bot(bot):
                doubt = await _call_get_doubt_friends(bot)
            if _is_onebot_v11_bot(bot):
                await _enrich_friend_request_rows_nicknames(bot, pending, doubt)
        rows.append({
            "self_id": sid,
            "connection_key": conn,
            "adapter": adapter,
            "online": online,
            "pending_friend_requests": pending,
            "doubt_friend_requests": doubt,
        })
    return {"bots": rows}


def _system_dict() -> dict[str, Any]:
    d = get_driver().config
    sup = getattr(d, "superusers", None) or set()
    try:
        n_sup = len(sup)
    except TypeError:
        n_sup = 0
    host = getattr(d, "host", None)
    port = getattr(d, "port", None)
    # 统一为可序列化的 host 字符串
    host_s: str | None = None if host is None else str(host)
    port_s: int | None
    if port is None:
        port_s = None
    else:
        try:
            port_s = int(port)
        except (TypeError, ValueError):
            port_s = None
    console = dict(_CONSOLE_EXTRA)
    sr = str(console.get("static_root", "") or "").strip()
    static_path = Path(sr) if sr else None
    _merge_console_version_from_disk(console, static_path)
    return {
        "nonebot2_driver": {
            "host": host_s,
            "port": port_s,
        },
        "superuser_count": n_sup,
        "server_time": time.time(),
        "plugin_count": sum(1 for r in _list_plugins_dict() if r.get("help_visible")),
        "bot_count": len(get_bots()),
        "console": console,
        "runtime": _runtime_metrics(),
    }


def _runtime_metrics() -> dict[str, Any]:
    cpu_percent: float | None = None
    cpu_per_core: list[float] = []
    cpu_load_avg: list[float] | None = None
    mem: dict[str, Any] = {"total": None, "used": None, "percent": None}
    try:
        import psutil  # type: ignore

        percpu = psutil.cpu_percent(interval=0.0, percpu=True)
        if isinstance(percpu, (list, tuple)) and len(percpu) > 0:
            cpu_per_core = [round(float(min(100.0, max(0.0, float(x)))), 2) for x in percpu]
            cpu_percent = round(sum(cpu_per_core) / len(cpu_per_core), 2)
        else:
            cpu_percent = float(psutil.cpu_percent(interval=0.0))
        vm = psutil.virtual_memory()
        mem = {
            "total": int(getattr(vm, "total", 0) or 0),
            "used": int(getattr(vm, "used", 0) or 0),
            "percent": round(float(getattr(vm, "percent", 0.0) or 0.0), 2),
        }
        av = getattr(vm, "available", None)
        if isinstance(av, (int, float)):
            mem["available"] = int(av)
        fr = getattr(vm, "free", None)
        if isinstance(fr, (int, float)):
            mem["free"] = int(fr)
        for _k in ("buffers", "cached", "shared", "wired"):
            _v = getattr(vm, _k, None)
            if isinstance(_v, (int, float)) and int(_v) > 0:
                mem[_k] = int(_v)
    except Exception:  # noqa: BLE001
        pass

    try:
        import os as _os_load

        if hasattr(_os_load, "getloadavg"):
            tup = _os_load.getloadavg()
            if isinstance(tup, (list, tuple)) and len(tup) >= 3:
                cpu_load_avg = [
                    round(float(tup[0]), 2),
                    round(float(tup[1]), 2),
                    round(float(tup[2]), 2),
                ]
    except Exception:  # noqa: BLE001
        pass

    disk = {"total": None, "used": None, "free": None, "percent": None}
    try:
        du = shutil.disk_usage("/")
        used = int(du.total - du.free)
        pct = (used / du.total * 100.0) if du.total else 0.0
        disk = {
            "total": int(du.total),
            "used": used,
            "free": int(du.free),
            "percent": round(pct, 2),
        }
    except Exception:  # noqa: BLE001
        pass

    hostname_s = (platform.node() or "").strip()
    if not hostname_s:
        try:
            hostname_s = (socket.gethostname() or "").strip()
        except Exception:  # noqa: BLE001
            hostname_s = ""
    if not hostname_s:
        hostname_s = (os.environ.get("COMPUTERNAME") or os.environ.get("HOSTNAME") or "").strip()

    boot_time: float | None = None
    try:
        import psutil as _psutil_boot  # type: ignore

        boot_time = float(_psutil_boot.boot_time())
    except Exception as e:  # noqa: BLE001
        logger.debug("Pallas-Bot 控制台: psutil.boot_time 不可用，将尝试其它方式 err={}", e)

    if boot_time is None and sys.platform == "win32":
        try:
            import ctypes

            ms = int(ctypes.windll.kernel32.GetTickCount64())
            boot_time = float(time.time() - ms / 1000.0)
        except Exception as e:  # noqa: BLE001
            logger.debug("Pallas-Bot 控制台: Windows GetTickCount64 推算启动时间失败 err={}", e)

    return {
        "platform": platform.platform(),
        "python": platform.python_version(),
        "hostname": hostname_s or None,
        "boot_time": boot_time,
        "cpu_percent": cpu_percent,
        "cpu_per_core": cpu_per_core,
        "cpu_load_avg": cpu_load_avg,
        "memory": mem,
        "disk": disk,
        "gpu": _gpu_metrics(),
    }


def _require_pallas_token_configured(
    plugin_config: Any,
    *,
    x_pallas_token: str | None,
    token: str | None,
) -> None:
    """所有控制台 API 共享的鉴权入口：与协议端共用会话（Cookie 或 X-Pallas-Token）。"""
    if bool(getattr(plugin_config, "pallas_webui_dev_mode", False)):
        return
    req = current_http_request()
    if req is None:
        raise HTTPException(status_code=500, detail="控制台鉴权缺少请求上下文")
    cookies = dict(req.cookies)
    if extract_session_from_request(
        cookies=cookies,
        header_token=x_pallas_token,
        query_token=token,
        cookie_token=None,
    ):
        return
    if not is_console_auth_configured():
        raise HTTPException(
            status_code=503,
            detail="统一控制台鉴权未初始化，请检查 data/pallas_console/",
        )
    raise HTTPException(status_code=401, detail="Invalid token")


# 历史调用点保留同名别名，写操作与受保护读操作行为已统一
_check_pallas_write_token = _require_pallas_token_configured


class _BotConfigPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    admins: list[int] | None = None
    disabled_plugins: list[str] | None = None
    auto_accept_friend: bool | None = None
    auto_accept_group: bool | None = None
    security: bool | None = None


class _GroupConfigPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    disabled_plugins: list[str] | None = None
    roulette_mode: int | None = Field(default=None, ge=0, le=1)
    banned: bool | None = None
    blocked_user_ids: list[int] | None = None


class _UserConfigPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    banned: bool | None = None


class _MongoAggregateBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    collection: str = Field(min_length=1, max_length=64)
    pipeline: list[Any] = Field(default_factory=list, max_length=16)


class _DbTableRowUpsertBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    table: str = Field(min_length=1, max_length=64)
    row_id: int = Field(ge=1)
    data: dict[str, Any] = Field(default_factory=dict)


class _AiExtensionConfigBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    base_url: str = Field(min_length=7, max_length=200)
    api_prefix: str = Field(default="/api", min_length=1, max_length=50)
    token: str = Field(default="", max_length=300)
    health_paths: list[str] = Field(default_factory=lambda: ["/health", "/api/health"], max_length=8)
    uvicorn_log_file: str = Field(default="", max_length=500)
    celery_log_file: str = Field(default="", max_length=500)
    timeout_sec: int = Field(default=8, ge=2, le=30)


class _AiNcmSendSmsBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    phone: str = Field(min_length=5, max_length=32)
    ctcode: int = Field(default=86, ge=1, le=999)


class _AiNcmVerifySmsBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    phone: str = Field(min_length=5, max_length=32)
    captcha: str = Field(min_length=2, max_length=16)
    ctcode: int = Field(default=86, ge=1, le=999)


class _HelpMenuVisibilityBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    hidden_plugins: list[str] = Field(default_factory=list, max_length=2000)


class _PluginConfigUpdateBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    values: dict[str, Any] = Field(default_factory=dict)


class _ChangeConsoleLoginBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    new_password: str = Field(min_length=1, max_length=256)


class _RequestActionBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    self_id: int = Field(ge=1)
    kind: Literal["friend", "group"]
    action: Literal["approve", "reject"] = "approve"
    source: Literal["pending", "doubt"] = "pending"
    user_id: int | None = Field(default=None, ge=1)
    group_id: int | None = Field(default=None, ge=1)


class _RequestBatchFriendRow(BaseModel):
    model_config = ConfigDict(extra="forbid")

    self_id: int = Field(ge=1)
    user_id: int = Field(ge=1)
    source: Literal["pending", "doubt"] = "pending"


class _RequestBatchGroupRow(BaseModel):
    model_config = ConfigDict(extra="forbid")

    self_id: int = Field(ge=1)
    user_id: int = Field(ge=1)
    group_id: int = Field(ge=1)


class _RequestActionsBatchBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: Literal["approve", "reject"] = "approve"
    friends: list[_RequestBatchFriendRow] = Field(default_factory=list, max_length=500)
    groups: list[_RequestBatchGroupRow] = Field(default_factory=list, max_length=500)


async def _apply_bot_config_patch(account: int, body: _BotConfigPatch) -> dict[str, Any]:
    from src.common.db import make_bot_config_repository
    from src.common.db.pallas_console_data import bot_config_to_public

    repo = make_bot_config_repository()
    await repo.get_or_create(account, disabled_plugins=[])
    fields: dict[str, Any] = {}
    for field_name, raw in body.model_dump(exclude_none=True).items():
        if field_name in ("admins", "disabled_plugins") and raw is not None:
            if field_name == "disabled_plugins":
                fields[field_name] = [str(s).strip() for s in raw if str(s).strip()]
            else:
                fields[field_name] = [int(x) for x in raw]
        else:
            fields[field_name] = raw
    await repo.upsert_fields(account, fields)
    if "disabled_plugins" in fields:
        from src.plugins.help.plugin_manager import invalidate_disabled_plugin_gate_cache

        await invalidate_disabled_plugin_gate_cache(bot_id=account)
    if "admins" in fields:
        from src.common.config.bot_admins_cache import invalidate_bot_admins_cache

        await invalidate_bot_admins_cache(account)
    doc = await repo.get(account, ignore_cache=True)
    if doc is None:
        raise HTTPException(status_code=500, detail="config upsert 后回读失败")
    return bot_config_to_public(doc)


async def _apply_group_config_patch(group_id: int, body: _GroupConfigPatch) -> dict[str, Any]:
    from src.common.db import make_group_config_repository
    from src.common.db.pallas_console_data import group_config_to_public

    repo = make_group_config_repository()
    await repo.get_or_create(group_id, disabled_plugins=[])
    fields: dict[str, Any] = {}
    for field_name, raw in body.model_dump(exclude_none=True).items():
        if field_name == "disabled_plugins" and raw is not None:
            fields[field_name] = [str(s).strip() for s in raw if str(s).strip()]
        elif field_name == "roulette_mode":
            fields[field_name] = 1 if int(raw) == 1 else 0
        elif field_name == "blocked_user_ids" and raw is not None:
            # 与 bot_config.admins 一致：逐项 int()，非法项由请求体验证阶段报错
            fields[field_name] = [int(x) for x in raw]
        else:
            fields[field_name] = raw
    await repo.upsert_fields(group_id, fields)
    if "blocked_user_ids" in fields:
        from src.plugins.blacklist import invalidate_group_ban_gate_cache

        await invalidate_group_ban_gate_cache(group_id)
    if "disabled_plugins" in fields:
        from src.plugins.help.plugin_manager import invalidate_disabled_plugin_gate_cache

        await invalidate_disabled_plugin_gate_cache(group_id=group_id)
    doc = await repo.get(group_id, ignore_cache=True)
    if doc is None:
        raise HTTPException(status_code=500, detail="config upsert 后回读失败")
    return group_config_to_public(doc)


async def _apply_user_config_patch(user_id: int, body: _UserConfigPatch) -> dict[str, Any]:
    from src.common.db import make_user_config_repository
    from src.common.db.pallas_console_data import user_config_to_public

    repo = make_user_config_repository()
    await repo.get_or_create(user_id, banned=False)
    await repo.upsert_fields(user_id, body.model_dump(exclude_none=True))
    doc = await repo.get(user_id, ignore_cache=True)
    if doc is None:
        raise HTTPException(status_code=500, detail="user_config upsert 后回读失败")
    return user_config_to_public(doc)


def _normalize_table_name(raw: str) -> str:
    name = (raw or "").strip().lower()
    aliases = {
        "config": "bot_config",
        "bot_config": "bot_config",
        "group_config": "group_config",
        "user_config": "user_config",
    }
    return aliases.get(name, "")


async def _get_db_table_row_public(table: str, row_id: int) -> dict[str, Any] | None:
    from src.common.db import make_bot_config_repository, make_group_config_repository, make_user_config_repository
    from src.common.db.pallas_console_data import bot_config_to_public, group_config_to_public, user_config_to_public

    t = _normalize_table_name(table)
    if t == "bot_config":
        repo = make_bot_config_repository()
        row = await repo.get(int(row_id), ignore_cache=True)
        return None if row is None else bot_config_to_public(row)
    if t == "group_config":
        repo = make_group_config_repository()
        row = await repo.get(int(row_id), ignore_cache=True)
        return None if row is None else group_config_to_public(row)
    if t == "user_config":
        repo = make_user_config_repository()
        row = await repo.get(int(row_id), ignore_cache=True)
        return None if row is None else user_config_to_public(row)
    raise ValueError("仅支持 config(bot_config)/group_config/user_config")


async def _upsert_db_table_row(table: str, row_id: int, data: dict[str, Any]) -> dict[str, Any]:
    from src.common.db import make_bot_config_repository, make_group_config_repository, make_user_config_repository

    t = _normalize_table_name(table)
    payload = dict(data or {})
    if t == "bot_config":
        repo = make_bot_config_repository()
        allowed = {
            "admins",
            "disabled_plugins",
            "auto_accept_friend",
            "auto_accept_group",
            "security",
            "taken_name",
            "drunk",
        }
        for k in payload:
            if k not in allowed:
                raise ValueError(f"bot_config 不允许字段: {k}")
        await repo.get_or_create(int(row_id), disabled_plugins=[])
        for k, v in payload.items():
            await repo.upsert_field(int(row_id), k, v)
        await repo.invalidate_cache()
        if "disabled_plugins" in payload:
            from src.plugins.help.plugin_manager import invalidate_disabled_plugin_gate_cache

            await invalidate_disabled_plugin_gate_cache(bot_id=int(row_id))
        if "admins" in payload:
            from src.common.config.bot_admins_cache import invalidate_bot_admins_cache

            await invalidate_bot_admins_cache(int(row_id))
        got = await _get_db_table_row_public("bot_config", int(row_id))
        if got is None:
            raise ValueError("upsert 后回读失败")
        return got
    if t == "group_config":
        repo = make_group_config_repository()
        allowed = {"disabled_plugins", "roulette_mode", "banned", "sing_progress", "blocked_user_ids"}
        for k in payload:
            if k not in allowed:
                raise ValueError(f"group_config 不允许字段: {k}")
        await repo.get_or_create(int(row_id), disabled_plugins=[])
        for k, v in payload.items():
            await repo.upsert_field(int(row_id), k, v)
        await repo.invalidate_cache()
        if "blocked_user_ids" in payload:
            from src.plugins.blacklist import invalidate_group_ban_gate_cache

            await invalidate_group_ban_gate_cache(int(row_id))
        if "disabled_plugins" in payload:
            from src.plugins.help.plugin_manager import invalidate_disabled_plugin_gate_cache

            await invalidate_disabled_plugin_gate_cache(group_id=int(row_id))
        got = await _get_db_table_row_public("group_config", int(row_id))
        if got is None:
            raise ValueError("upsert 后回读失败")
        return got
    if t == "user_config":
        repo = make_user_config_repository()
        allowed = {"banned"}
        for k in payload:
            if k not in allowed:
                raise ValueError(f"user_config 不允许字段: {k}")
        await repo.get_or_create(int(row_id), banned=False)
        for k, v in payload.items():
            await repo.upsert_field(int(row_id), k, v)
        await repo.invalidate_cache()
        got = await _get_db_table_row_public("user_config", int(row_id))
        if got is None:
            raise ValueError("upsert 后回读失败")
        return got
    raise ValueError("仅支持 config(bot_config)/group_config/user_config")


async def _delete_db_table_row(table: str, row_id: int) -> bool:
    from src.common.db import get_db_backend

    t = _normalize_table_name(table)
    if not t:
        raise ValueError("仅支持 config(bot_config)/group_config/user_config")
    backend = get_db_backend()
    if backend == "mongodb":
        from src.common.db.modules import BotConfigModule, GroupConfigModule, UserConfigModule

        model_map = {
            "bot_config": (BotConfigModule, "account"),
            "group_config": (GroupConfigModule, "group_id"),
            "user_config": (UserConfigModule, "user_id"),
        }
        model, key = model_map[t]
        doc = await model.find_one({key: int(row_id)})
        if doc is None:
            return False
        await doc.delete()
        return True
    if backend in ("postgres", "postgresql", "pg"):
        from sqlalchemy import delete

        from src.common.db.repository_pg import BotConfigRow, GroupConfigRow, UserConfigRow, get_session

        row_map = {
            "bot_config": (BotConfigRow, "account"),
            "group_config": (GroupConfigRow, "group_id"),
            "user_config": (UserConfigRow, "user_id"),
        }
        row_class, key = row_map[t]
        async with get_session() as session:
            result = await session.execute(delete(row_class).where(getattr(row_class, key) == int(row_id)))
            await session.commit()
            return bool(int(result.rowcount or 0) > 0)
    raise ValueError(f"不支持的 DB 后端: {backend}")


def register_extended_api(
    app,
    *,
    api_base: str,
    plugin_config: Config,
) -> None:
    ensure_console_metrics_hooks()
    x = (api_base or "/pallas/api").strip()
    if not x.startswith("/"):
        x = "/" + x
    x = x.rstrip("/")

    async def _pallas_token_dep(
        token: str | None = Query(default=None),
        x_pallas_token: str | None = Header(default=None, alias="X-Pallas-Token"),
    ) -> None:
        """全局依赖：所有控制台 API（除 /health 外）必须携带有效 token。"""
        _require_pallas_token_configured(
            plugin_config,
            x_pallas_token=x_pallas_token,
            token=token,
        )

    class _AuthLoginBody(BaseModel):
        model_config = ConfigDict(extra="forbid")

        password: str = Field(min_length=1, max_length=512)

    router_pub = APIRouter(tags=["Pallas-Bot 控制台"])

    @router_pub.post(f"{x}/auth/login", include_in_schema=False)
    async def _auth_login(request: Request, body: _AuthLoginBody) -> JSONResponse:
        from src.common.webui.console_login import SESSION_COOKIE_NAME, SESSION_TTL_SEC

        if not verify_console_password(body.password):
            raise HTTPException(status_code=401, detail="口令错误")
        tok = mint_session_token()
        resp = JSONResponse({"ok": True, "data": {"token": tok}})
        resp.set_cookie(
            key=SESSION_COOKIE_NAME,
            value=tok,
            max_age=SESSION_TTL_SEC,
            httponly=True,
            samesite="lax",
            secure=request.url.scheme == "https",
            path="/",
        )
        clear_extended_read_cache()
        return resp

    router = APIRouter(tags=["Pallas-Bot 控制台"], dependencies=[Depends(_pallas_token_dep)])

    @router.get(f"{x}/system", include_in_schema=True)
    async def _system() -> JSONResponse:
        async def _load() -> dict[str, Any]:
            return _system_dict()

        data = await _cached_read(key="system", loader=_load, ttl_sec=0.8, stale_sec=8.0)
        return JSONResponse({"ok": True, "data": data})

    @router.get(f"{x}/shard-registry", include_in_schema=True)
    async def _shard_registry() -> JSONResponse:
        from src.common.shard.registry import get_shard_registry, rebalance_hint
        from src.common.shard.registry.config import get_shard_registry_settings

        reg = get_shard_registry()
        settings = get_shard_registry_settings()
        return JSONResponse({
            "ok": True,
            "data": {
                "settings": settings.model_dump(mode="json"),
                "registry": reg.model_dump(mode="json"),
                "summary": rebalance_hint(),
            },
        })

    @router.get(f"{x}/message-stats", include_in_schema=True)
    async def _message_stats(
        self_id: int | None = Query(default=None, ge=1),
    ) -> JSONResponse:
        async def _load() -> dict[str, Any]:
            return await _message_stats_overview(self_id=str(self_id) if self_id is not None else None)

        key = f"message-stats:{self_id or 'all'}"
        data = await _cached_read(key=key, loader=_load, ttl_sec=2.0, stale_sec=10.0)
        return JSONResponse({"ok": True, "data": data})

    @router.get(f"{x}/plugin-run-stats", include_in_schema=True)
    async def _plugin_run_stats(
        self_id: int | None = Query(default=None, ge=1),
        log_source: str | None = Query(
            default=None,
            description="日志报错来源筛选：all|hub|worker-N",
        ),
        tb_limit: int = Query(
            default=0,
            ge=0,
            le=200_000,
            description="log_error_log 单条 traceback 最大字符数，0 表示不截断",
        ),
    ) -> JSONResponse:
        src = (log_source or "all").strip() or "all"

        async def _load() -> dict[str, Any]:
            return _plugin_run_stats_overview(
                self_id=str(self_id) if self_id is not None else None,
                log_source=src,
                tb_limit=tb_limit,
            )

        key = f"plugin-run-stats:{self_id or 'all'}:logsrc:{src}:tbl:{tb_limit}"
        data = await _cached_read(key=key, loader=_load, ttl_sec=2.0, stale_sec=10.0)
        return JSONResponse({"ok": True, "data": data})

    @router.get(f"{x}/console-daily-stats", include_in_schema=True)
    async def _console_daily_stats(
        self_id: int | None = Query(default=None, ge=1),
        start: str | None = Query(default=None, description="YYYY-MM-DD，含当日"),
        end: str | None = Query(default=None, description="YYYY-MM-DD，含当日"),
    ) -> JSONResponse:
        async def _load() -> dict[str, Any]:
            return _console_daily_stats_payload(
                self_id=str(self_id) if self_id is not None else None,
                start=start,
                end=end,
            )

        key = f"console-daily-stats:{self_id or 'all'}:{start or ''}:{end or ''}"
        data = await _cached_read(key=key, loader=_load, ttl_sec=3.0, stale_sec=15.0)
        return JSONResponse({"ok": True, "data": data})

    @router.get(f"{x}/plugins", include_in_schema=True)
    async def _plugins() -> JSONResponse:
        async def _load() -> list[dict[str, Any]]:
            return _list_plugins_dict()

        data = await _cached_read(key="plugins", loader=_load, ttl_sec=1.6, stale_sec=25.0)
        return JSONResponse({"ok": True, "data": data})

    @router.get(f"{x}/plugins/help-menu-visibility", include_in_schema=True)
    async def _plugins_help_menu_visibility() -> JSONResponse:
        try:
            from src.plugins.help.visibility import load_help_hidden_plugins, resolve_help_ignored_plugins

            data = {
                "hidden_plugins": load_help_hidden_plugins(),
                "ignored_plugins": resolve_help_ignored_plugins(),
            }
        except Exception as e:  # noqa: BLE001
            raise HTTPException(status_code=500, detail=str(e)) from e
        return JSONResponse({"ok": True, "data": data})

    @router.put(f"{x}/plugins/help-menu-visibility", include_in_schema=True)
    async def _plugins_help_menu_visibility_put(
        body: _HelpMenuVisibilityBody,
        token: str | None = Query(default=None),
        x_pallas_token: str | None = Header(default=None, alias="X-Pallas-Token"),
    ) -> JSONResponse:
        _check_pallas_write_token(plugin_config, x_pallas_token=x_pallas_token, token=token)
        try:
            from src.plugins.help.visibility import save_help_hidden_plugins

            hidden = save_help_hidden_plugins(body.hidden_plugins)
        except Exception as e:  # noqa: BLE001
            raise HTTPException(status_code=500, detail=str(e)) from e
        _drop_read_cache(("plugins",))
        return JSONResponse({"ok": True, "data": {"hidden_plugins": hidden}})

    @router.get(f"{x}/plugins/{{plugin_name}}/config", include_in_schema=True)
    async def _plugin_config_get(plugin_name: str) -> JSONResponse:
        try:
            data = plugin_config_payload(plugin_name)
        except ValueError:
            # 无 config.py 或配置模型不可用时返回空配置，前端以“不可编辑”展示
            data = {"plugin": plugin_name, "module": "", "fields": []}
        except Exception as e:  # noqa: BLE001
            raise HTTPException(status_code=500, detail=str(e)) from e
        return JSONResponse({"ok": True, "data": data})

    @router.put(f"{x}/plugins/{{plugin_name}}/config", include_in_schema=True)
    async def _plugin_config_put(
        plugin_name: str,
        body: _PluginConfigUpdateBody,
        token: str | None = Query(default=None),
        x_pallas_token: str | None = Header(default=None, alias="X-Pallas-Token"),
    ) -> JSONResponse:
        _check_pallas_write_token(plugin_config, x_pallas_token=x_pallas_token, token=token)
        try:
            data = apply_plugin_config_patch(plugin_name, dict(body.values or {}))
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e
        except Exception as e:  # noqa: BLE001
            from pydantic import ValidationError

            if isinstance(e, ValidationError):
                from src.common.webui.plugin_api import format_validation_error

                raise HTTPException(status_code=400, detail=format_validation_error(e)) from e
            raise HTTPException(status_code=500, detail=str(e)) from e
        return JSONResponse({"ok": True, "data": data})

    @router.post(f"{x}/plugins/{{plugin_name}}/config-check", include_in_schema=True)
    async def _plugin_config_check(
        plugin_name: str,
        body: _PluginConfigUpdateBody,
        token: str | None = Query(default=None),
        x_pallas_token: str | None = Header(default=None, alias="X-Pallas-Token"),
    ) -> JSONResponse:
        _check_pallas_write_token(plugin_config, x_pallas_token=x_pallas_token, token=token)
        if plugin_name != "pallas_image":
            raise HTTPException(status_code=400, detail="该插件暂不支持配置检测")
        from src.plugins.pallas_image.gateway_probe import (
            format_gateway_status_lines,
            image_gen_settings_from_draft,
            probe_all_backends,
        )

        draft = dict(body.values or {})
        try:
            settings = image_gen_settings_from_draft(draft)
        except Exception as e:  # noqa: BLE001
            from pydantic import ValidationError

            if isinstance(e, ValidationError):
                from src.common.webui.plugin_api import format_validation_error

                raise HTTPException(status_code=400, detail=format_validation_error(e)) from e
            raise HTTPException(status_code=400, detail=str(e)) from e
        results = await probe_all_backends(settings)
        if not results:
            lines = ["牛牛画画：尚未配置可用网关（需 base_url、api_key）"]
            return JSONResponse(
                {
                    "ok": True,
                    "data": {"lines": lines, "results": []},
                },
            )
        lines = format_gateway_status_lines(results)
        return JSONResponse(
            {
                "ok": True,
                "data": {
                    "lines": lines,
                    "results": [r.to_dict() for r in results],
                },
            },
        )

    @router.get(f"{x}/common-config/sections", include_in_schema=True)
    async def _common_config_sections_list() -> JSONResponse:
        from src.common.webui.env_sections import list_webui_env_sections

        return JSONResponse({"ok": True, "data": list_webui_env_sections()})

    @router.get(f"{x}/common-config/{{section_id}}", include_in_schema=True)
    async def _common_config_get(section_id: str) -> JSONResponse:
        from src.common.webui.env_sections import webui_env_section_payload

        try:
            data = webui_env_section_payload(section_id)
        except ValueError as e:
            raise HTTPException(status_code=404, detail=str(e)) from e
        return JSONResponse({"ok": True, "data": data})

    @router.put(f"{x}/common-config/{{section_id}}", include_in_schema=True)
    async def _common_config_put(
        section_id: str,
        body: _PluginConfigUpdateBody,
        token: str | None = Query(default=None),
        x_pallas_token: str | None = Header(default=None, alias="X-Pallas-Token"),
    ) -> JSONResponse:
        _check_pallas_write_token(plugin_config, x_pallas_token=x_pallas_token, token=token)
        from src.common.webui.env_sections import apply_webui_env_section_patch

        try:
            data = apply_webui_env_section_patch(section_id, dict(body.values or {}))
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e
        except Exception as e:  # noqa: BLE001
            raise HTTPException(status_code=500, detail=str(e)) from e
        return JSONResponse({"ok": True, "data": data})

    @router.post(
        f"{x}/common-config/service_gateways/connectivity-check",
        include_in_schema=True,
    )
    async def _service_gateways_connectivity_check(
        body: _PluginConfigUpdateBody,
        token: str | None = Query(default=None),
        x_pallas_token: str | None = Header(default=None, alias="X-Pallas-Token"),
    ) -> JSONResponse:
        _check_pallas_write_token(plugin_config, x_pallas_token=x_pallas_token, token=token)
        from src.common.service_probe import format_probe_lines
        from src.plugins.connectivity.probe_collect import probe_all_connectivity_from_draft

        try:
            results = await probe_all_connectivity_from_draft(dict(body.values or {}))
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e
        lines = format_probe_lines(results)
        return JSONResponse({
            "ok": True,
            "data": {
                "lines": lines,
                "results": [r.to_dict() for r in results],
            },
        })

    @router.get(f"{x}/bots", include_in_schema=True)
    async def _bots() -> JSONResponse:
        async def _load() -> list[dict[str, Any]]:
            return _list_bots_dict()

        data = await _cached_read(key="bots", loader=_load, ttl_sec=0.9, stale_sec=15.0)
        return JSONResponse({"ok": True, "data": data})

    @router.get(f"{x}/logs", include_in_schema=True)
    async def _logs(
        n: int = Query(default=200, ge=1, le=plugin_config.pallas_webui_log_lines_max),
        scope: Annotated[
            LogScope,
            Query(
                description=(
                    "all=全部（分片 hub 时合并 hub 环与各 worker 落盘日志）；"
                    "webui=pallas_webui 或 [pallas-webui]；"
                    "protocol=pallas_protocol 或 [pallas-protocol]"
                ),
            ),
        ] = "all",
        source: str | None = Query(
            default=None,
            description="分片来源：all|hub|worker-0|worker-1…（默认 all，不含 bootstrap）",
        ),
    ) -> JSONResponse:
        _ensure_log_sink()
        from src.common.web import tail_nonebot_log_entries_scoped, tail_nonebot_log_lines_scoped

        sharded_logs = False
        log_sources: list[str] = []
        try:
            from src.common.bot_runtime.roles import is_sharded_hub

            if is_sharded_hub():
                sharded_logs = True
                from src.common.shard.logs.view import list_shard_log_sources

                log_sources = list_shard_log_sources()
        except Exception:
            pass
        src = (source or "all").strip() or "all"
        return JSONResponse({
            "ok": True,
            "data": {
                "lines": tail_nonebot_log_lines_scoped(n, scope, source=src),
                "entries": tail_nonebot_log_entries_scoped(n, scope, source=src),
                "max": plugin_config.pallas_webui_log_lines_max,
                "scope": scope,
                "source": src,
                "sharded_logs": sharded_logs,
                "log_sources": log_sources,
            },
        })

    @router.get(
        f"{x}/logs/stream",
        include_in_schema=True,
    )
    async def _logs_stream(
        scope: Annotated[
            LogScope,
            Query(
                description=("all=全部；webui=仅 pallas_webui 相关；protocol=仅 pallas_protocol 相关"),
            ),
        ] = "all",
        source: str | None = Query(
            default=None,
            description="分片来源：all|hub|worker-N（与 GET /logs 一致）",
        ),
    ) -> StreamingResponse:
        _ensure_log_sink()
        from src.common.web import iter_nonebot_log_sse

        src = (source or "all").strip() or "all"
        return StreamingResponse(
            iter_nonebot_log_sse(scope, source=src),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )

    @router.get(
        f"{x}/plugin-config-hint",
        include_in_schema=True,
    )
    async def _plugin_config_hint() -> JSONResponse:
        return JSONResponse({
            "ok": True,
            "data": {
                "message": "",
            },
        })

    @router.get(f"{x}/db/overview", include_in_schema=True)
    async def _db_overview() -> JSONResponse:
        from src.common.db.pallas_console_data import database_overview

        try:
            data = await _cached_read(
                key="db_overview",
                loader=database_overview,
                ttl_sec=1.5,
                stale_sec=30.0,
            )
        except Exception as e:  # noqa: BLE001
            logger.exception("Pallas-Bot 控制台: 数据库概览失败")
            raise HTTPException(status_code=500, detail=str(e)) from e
        return JSONResponse({"ok": True, "data": data})

    @router.post(f"{x}/db/mongodb/aggregate", include_in_schema=True)
    async def _db_mongo_aggregate(
        body: _MongoAggregateBody,
        token: str | None = Query(default=None),
        x_pallas_token: str | None = Header(default=None, alias="X-Pallas-Token"),
    ) -> JSONResponse:
        """受限 MongoDB aggregate（只读阶段白名单 + 强制结果上限）；须携带有效控制台会话。"""
        _require_pallas_token_configured(
            plugin_config,
            x_pallas_token=x_pallas_token,
            token=token,
        )
        from src.common.db.pallas_console_data import mongo_aggregate_console

        try:
            rows = await mongo_aggregate_console(
                collection=body.collection,
                pipeline=body.pipeline,
            )
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e
        except Exception as e:  # noqa: BLE001
            logger.exception("Pallas-Bot 控制台: Mongo aggregate 失败")
            raise HTTPException(status_code=500, detail=str(e)) from e
        return JSONResponse({"ok": True, "data": {"rows": rows, "truncated_to": len(rows)}})

    @router.get(f"{x}/db/table-row", include_in_schema=True)
    async def _db_table_row_get(
        table: str = Query(..., description="config|bot_config|group_config|user_config"),
        row_id: int = Query(..., ge=1, description="主键值"),
    ) -> JSONResponse:
        try:
            data = await _get_db_table_row_public(table, int(row_id))
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e
        except Exception as e:  # noqa: BLE001
            logger.exception("Pallas-Bot 控制台: 读取表行失败")
            raise HTTPException(status_code=500, detail=str(e)) from e
        if data is None:
            raise HTTPException(status_code=404, detail="未找到该行")
        return JSONResponse({"ok": True, "data": data})

    @router.put(f"{x}/db/table-row", include_in_schema=True)
    async def _db_table_row_put(
        body: _DbTableRowUpsertBody,
        token: str | None = Query(default=None),
        x_pallas_token: str | None = Header(default=None, alias="X-Pallas-Token"),
    ) -> JSONResponse:
        _check_pallas_write_token(plugin_config, x_pallas_token=x_pallas_token, token=token)
        if not body.data:
            raise HTTPException(status_code=400, detail="data 为空")
        try:
            data = await _upsert_db_table_row(body.table, int(body.row_id), dict(body.data))
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e
        except Exception as e:  # noqa: BLE001
            logger.exception("Pallas-Bot 控制台: 写入表行失败")
            raise HTTPException(status_code=500, detail=str(e)) from e
        _drop_read_cache(
            ("db_overview", "bot_configs_list", "group_configs_list", "user_configs_list", "instances"),
        )
        return JSONResponse({"ok": True, "data": data})

    @router.delete(f"{x}/db/table-row", include_in_schema=True)
    async def _db_table_row_delete(
        table: str = Query(..., description="config|bot_config|group_config|user_config"),
        row_id: int = Query(..., ge=1, description="主键值"),
        token: str | None = Query(default=None),
        x_pallas_token: str | None = Header(default=None, alias="X-Pallas-Token"),
    ) -> JSONResponse:
        _check_pallas_write_token(plugin_config, x_pallas_token=x_pallas_token, token=token)
        try:
            deleted = await _delete_db_table_row(table, int(row_id))
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e
        except Exception as e:  # noqa: BLE001
            logger.exception("Pallas-Bot 控制台: 删除表行失败")
            raise HTTPException(status_code=500, detail=str(e)) from e
        _drop_read_cache(
            ("db_overview", "bot_configs_list", "group_configs_list", "user_configs_list", "instances"),
        )
        if not deleted:
            raise HTTPException(status_code=404, detail="未找到该行")
        return JSONResponse({"ok": True, "data": {"deleted": True}})

    @router.get(f"{x}/instances", include_in_schema=True)
    async def _instances() -> JSONResponse:
        from src.common.db.pallas_console_data import list_all_bot_configs_public, pallas_protocol_snapshot

        async def _load() -> dict[str, Any]:
            db_bots = await list_all_bot_configs_public()
            snap = pallas_protocol_snapshot()
            bot_profiles = await _collect_online_bot_profiles()
            payload: dict[str, Any] = {
                "nonebot_bots": _list_bots_dict(),
                "db_bot_configs": db_bots,
                "pallas_protocol": snap,
                "bot_profiles": bot_profiles,
            }
            if snap is not None:
                payload["napcat"] = snap
            return payload

        try:
            payload = await _cached_read(
                key="instances",
                loader=_load,
                ttl_sec=1.0,
                stale_sec=20.0,
            )
        except Exception as e:  # noqa: BLE001
            logger.exception("Pallas-Bot 控制台: 加载实例视图失败")
            raise HTTPException(status_code=500, detail=str(e)) from e
        return JSONResponse({"ok": True, "data": payload})

    @router.get(f"{x}/bot-configs", include_in_schema=True)
    async def _bot_configs_list() -> JSONResponse:
        from src.common.db.pallas_console_data import list_all_bot_configs_public

        try:
            rows = await _cached_read(
                key="bot_configs_list",
                loader=list_all_bot_configs_public,
                ttl_sec=1.0,
                stale_sec=20.0,
            )
        except Exception as e:  # noqa: BLE001
            raise HTTPException(status_code=500, detail=str(e)) from e
        return JSONResponse({"ok": True, "data": rows})

    @router.get(f"{x}/bot-configs/{{account}}", include_in_schema=True)
    async def _bot_config_one(
        account: int,
    ) -> JSONResponse:
        from src.common.db import make_bot_config_repository
        from src.common.db.pallas_console_data import bot_config_to_public

        repo = make_bot_config_repository()
        doc = await repo.get(account, ignore_cache=True)
        if doc is None:
            raise HTTPException(status_code=404, detail="未找到该账号的 Bot 配置")
        return JSONResponse({"ok": True, "data": bot_config_to_public(doc)})

    @router.put(f"{x}/bot-configs/{{account}}", include_in_schema=True)
    async def _bot_config_put(
        account: int,
        body: _BotConfigPatch,
        token: str | None = Query(default=None),
        x_pallas_token: str | None = Header(default=None, alias="X-Pallas-Token"),
    ) -> JSONResponse:
        _check_pallas_write_token(plugin_config, x_pallas_token=x_pallas_token, token=token)
        if not body.model_dump(exclude_none=True):
            raise HTTPException(status_code=400, detail="body 为空")
        try:
            data = await _apply_bot_config_patch(account, body)
        except HTTPException:
            raise
        except Exception as e:  # noqa: BLE001
            logger.exception("Pallas-Bot 控制台: 更新 Bot 配置失败")
            raise HTTPException(status_code=500, detail=str(e)) from e
        _drop_read_cache(("instances", "bot_configs_list", "db_overview"))
        return JSONResponse({"ok": True, "data": data})

    @router.get(f"{x}/group-configs", include_in_schema=True)
    async def _group_configs_list(
        limit: int = Query(default=1000, ge=1, le=10_000),
        self_id: int | None = Query(default=None, description="Bot QQ；传入时仅返回该 Bot 所在群的配置"),
    ) -> JSONResponse:
        from src.common.db.pallas_console_data import list_group_configs_by_ids_public, list_group_configs_public

        # 按账号过滤：拉取 Bot 的群列表，再从 DB 取对应群配置并合并（走 OneBot，结果短时缓存）
        if self_id is not None:
            cache_key_bot = f"group_configs_bot:{int(self_id)}:{int(limit)}"

            async def _load_bot_merge() -> dict[str, Any]:
                target_inner = str(int(self_id))
                bot_inner = None
                for b in get_bots().values():
                    if str(getattr(b, "self_id", "") or "") == target_inner:
                        bot_inner = b
                        break
                if bot_inner is None:
                    raise HTTPException(status_code=404, detail="指定账号当前未连接")
                if not _is_onebot_v11_bot(bot_inner):
                    raise HTTPException(status_code=400, detail="当前连接不是 OneBot V11，无法拉取群列表")

                groups_inner, err, truncated = await _call_get_group_list(bot_inner, limit=int(limit))
                group_ids = [int(g["group_id"]) for g in groups_inner]

                try:
                    db_configs = await list_group_configs_by_ids_public(group_ids)
                except Exception as e:  # noqa: BLE001
                    raise HTTPException(status_code=500, detail=str(e)) from e

                rows_inner: list[dict[str, Any]] = []
                for g in groups_inner:
                    gid = int(g["group_id"])
                    cfg = db_configs.get(
                        gid,
                        {
                            "group_id": gid,
                            "roulette_mode": 1,
                            "banned": False,
                            "sing_progress": None,
                            "disabled_plugins": [],
                            "blocked_user_ids": [],
                        },
                    )
                    rows_inner.append({
                        **cfg,
                        "group_name": g.get("group_name", ""),
                        "member_count": g.get("member_count", 0),
                    })

                return {
                    "rows": rows_inner,
                    "meta": {
                        "limit": limit,
                        "self_id": target_inner,
                        "from_bot": True,
                        "error": err,
                        "truncated": truncated,
                    },
                }

            try:
                packed = await _cached_read(
                    key=cache_key_bot,
                    loader=_load_bot_merge,
                    ttl_sec=2.0,
                    stale_sec=22.0,
                )
            except HTTPException:
                raise
            except Exception as e:  # noqa: BLE001
                logger.exception("Pallas-Bot 控制台: 群配置（按 Bot）加载失败")
                raise HTTPException(status_code=500, detail=str(e)) from e

            return JSONResponse({
                "ok": True,
                "data": packed["rows"],
                "meta": packed["meta"],
            })

        # 原有行为：返回 DB 中所有群配置
        cache_key = f"group_configs_list:{int(limit)}"

        async def _load() -> list[dict[str, Any]]:
            return await list_group_configs_public(limit)

        try:
            rows = await _cached_read(key=cache_key, loader=_load, ttl_sec=1.0, stale_sec=20.0)
        except Exception as e:  # noqa: BLE001
            raise HTTPException(status_code=500, detail=str(e)) from e
        return JSONResponse({"ok": True, "data": rows, "meta": {"limit": limit}})

    @router.get(f"{x}/group-configs/{{group_id}}", include_in_schema=True)
    async def _group_config_one(
        group_id: int,
    ) -> JSONResponse:
        from src.common.db import make_group_config_repository
        from src.common.db.pallas_console_data import group_config_to_public

        repo = make_group_config_repository()
        doc, _created = await repo.get_or_create(group_id, disabled_plugins=[])
        return JSONResponse({"ok": True, "data": group_config_to_public(doc)})

    @router.put(f"{x}/group-configs/{{group_id}}", include_in_schema=True)
    async def _group_config_put(
        group_id: int,
        body: _GroupConfigPatch,
        token: str | None = Query(default=None),
        x_pallas_token: str | None = Header(default=None, alias="X-Pallas-Token"),
    ) -> JSONResponse:
        _check_pallas_write_token(plugin_config, x_pallas_token=x_pallas_token, token=token)
        if not body.model_dump(exclude_none=True):
            raise HTTPException(status_code=400, detail="body 为空")
        try:
            data = await _apply_group_config_patch(group_id, body)
        except HTTPException:
            raise
        except Exception as e:  # noqa: BLE001
            logger.exception("Pallas-Bot 控制台: 更新群配置失败")
            raise HTTPException(status_code=500, detail=str(e)) from e
        _drop_read_cache(("group_configs_list", "db_overview", "group_configs_bot:"))
        return JSONResponse({"ok": True, "data": data})

    @router.get(f"{x}/user-configs", include_in_schema=True)
    async def _user_configs_list(
        limit: int = Query(default=1000, ge=1, le=10_000),
    ) -> JSONResponse:
        from src.common.db.pallas_console_data import list_user_configs_public

        cache_key = f"user_configs_list:{int(limit)}"

        async def _load() -> list[dict[str, Any]]:
            return await list_user_configs_public(limit)

        try:
            rows = await _cached_read(key=cache_key, loader=_load, ttl_sec=1.0, stale_sec=20.0)
        except Exception as e:  # noqa: BLE001
            raise HTTPException(status_code=500, detail=str(e)) from e
        return JSONResponse({"ok": True, "data": rows, "meta": {"limit": limit}})

    @router.get(f"{x}/user-configs/{{user_id}}", include_in_schema=True)
    async def _user_config_one(
        user_id: int,
    ) -> JSONResponse:
        from src.common.db import make_user_config_repository
        from src.common.db.pallas_console_data import user_config_to_public

        repo = make_user_config_repository()
        doc, _created = await repo.get_or_create(user_id, banned=False)
        return JSONResponse({"ok": True, "data": user_config_to_public(doc)})

    @router.put(f"{x}/user-configs/{{user_id}}", include_in_schema=True)
    async def _user_config_put(
        user_id: int,
        body: _UserConfigPatch,
        token: str | None = Query(default=None),
        x_pallas_token: str | None = Header(default=None, alias="X-Pallas-Token"),
    ) -> JSONResponse:
        _check_pallas_write_token(plugin_config, x_pallas_token=x_pallas_token, token=token)
        if not body.model_dump(exclude_none=True):
            raise HTTPException(status_code=400, detail="body 为空")
        try:
            data = await _apply_user_config_patch(user_id, body)
        except HTTPException:
            raise
        except Exception as e:  # noqa: BLE001
            logger.exception("Pallas-Bot 控制台: 更新 User 配置失败")
            raise HTTPException(status_code=500, detail=str(e)) from e
        _drop_read_cache(("db_overview", "user_configs_list"))
        return JSONResponse({"ok": True, "data": data})

    @router.get(f"{x}/ai-extension/config", include_in_schema=True)
    async def _ai_extension_get() -> JSONResponse:
        return JSONResponse({"ok": True, "data": _load_ai_extension_config()})

    @router.put(f"{x}/ai-extension/config", include_in_schema=True)
    async def _ai_extension_put(
        body: _AiExtensionConfigBody,
        token: str | None = Query(default=None),
        x_pallas_token: str | None = Header(default=None, alias="X-Pallas-Token"),
    ) -> JSONResponse:
        _check_pallas_write_token(plugin_config, x_pallas_token=x_pallas_token, token=token)
        clean = _save_ai_extension_config(body.model_dump())
        return JSONResponse({"ok": True, "data": clean})

    @router.post(f"{x}/ai-extension/test", include_in_schema=True)
    async def _ai_extension_test() -> JSONResponse:
        import urllib.error
        import urllib.request

        cfg = _load_ai_extension_config()
        tried_urls: list[str] = []
        headers: dict[str, str] = {}
        if cfg.get("token"):
            headers["Authorization"] = f"Bearer {cfg['token']}"
        base = str(cfg["base_url"]).rstrip("/")
        paths = [str(x) for x in cfg.get("health_paths", []) if str(x).strip()]
        last_error = "未命中可用健康检查地址"
        last_status: int | None = None
        last_url = ""
        for p in paths:
            pp = p if p.startswith("/") else f"/{p}"
            health_url = f"{base}{pp}"
            tried_urls.append(health_url)
            req = urllib.request.Request(health_url, method="GET", headers=headers)

            def _do_request(_req=req) -> int:
                with urllib.request.urlopen(_req, timeout=float(cfg["timeout_sec"])) as resp:
                    return int(getattr(resp, "status", 200) or 200)

            try:
                status_code = await asyncio.to_thread(_do_request)
                return JSONResponse(
                    {
                        "ok": True,
                        "data": {
                            "ok": 200 <= status_code < 300,
                            "status_code": status_code,
                            "health_url": health_url,
                            "tried_urls": tried_urls,
                            "error": None,
                        },
                    },
                )
            except urllib.error.HTTPError as e:
                last_status = int(getattr(e, "code", 0) or 0)
                last_error = str(e)
                last_url = health_url
            except Exception as e:  # noqa: BLE001
                last_status = None
                last_error = str(e)
                last_url = health_url
        return JSONResponse(
            {
                "ok": True,
                "data": {
                    "ok": False,
                    "status_code": last_status,
                    "health_url": last_url,
                    "tried_urls": tried_urls,
                    "error": last_error,
                },
            },
        )

    async def _ai_extension_http_json(
        *,
        method: Literal["GET", "POST"],
        path: str,
        body: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        import urllib.error
        import urllib.request

        cfg = _load_ai_extension_config()
        base = str(cfg["base_url"]).rstrip("/")
        api_prefix = str(cfg.get("api_prefix", "/api")).strip() or "/api"
        if not api_prefix.startswith("/"):
            api_prefix = "/" + api_prefix
        merged_path = f"{api_prefix.rstrip('/')}/{path.lstrip('/')}"
        p = merged_path if merged_path.startswith("/") else f"/{merged_path}"
        url = f"{base}{p}"
        headers = {"Content-Type": "application/json"}
        if cfg.get("token"):
            headers["Authorization"] = f"Bearer {cfg['token']}"
        data_b = json.dumps(body or {}).encode("utf-8") if method == "POST" else None
        req = urllib.request.Request(url, method=method, headers=headers, data=data_b)

        def _do() -> tuple[int, str]:
            with urllib.request.urlopen(req, timeout=float(cfg["timeout_sec"])) as resp:
                status_code = int(getattr(resp, "status", 200) or 200)
                txt = resp.read().decode("utf-8", errors="ignore")
                return status_code, txt

        try:
            status_code, txt = await asyncio.to_thread(_do)
            try:
                data = json.loads(txt) if txt else {}
            except Exception:  # noqa: BLE001
                data = {"raw": txt}
            return {"ok": 200 <= status_code < 300, "status_code": status_code, "url": url, "data": data, "error": None}
        except urllib.error.HTTPError as e:
            return {
                "ok": False,
                "status_code": int(getattr(e, "code", 0) or 0),
                "url": url,
                "data": {},
                "error": str(e),
            }
        except Exception as e:  # noqa: BLE001
            return {"ok": False, "status_code": None, "url": url, "data": {}, "error": str(e)}

    @router.get(f"{x}/ai-extension/logs", include_in_schema=True)
    async def _ai_extension_logs(
        kind: Literal["uvicorn", "celery"] = Query(default="uvicorn"),
        n: int = Query(default=200, ge=1, le=2000),
    ) -> JSONResponse:
        cfg = _load_ai_extension_config()
        path_s = str(cfg["uvicorn_log_file"] if kind == "uvicorn" else cfg["celery_log_file"])
        # 防御深度：即便规范化阶段已校验，读取前再检一次，杜绝持久化污染绕过
        if not _is_allowed_log_path(path_s):
            return JSONResponse(
                {
                    "ok": True,
                    "data": {"kind": kind, "path": path_s, "lines": [], "error": "日志路径越界，已拒绝"},
                },
            )
        p = Path(path_s)
        if not await asyncio.to_thread(p.exists):
            return JSONResponse(
                {
                    "ok": True,
                    "data": {"kind": kind, "path": path_s, "lines": [], "error": "日志文件不存在"},
                },
            )
        try:
            text = await asyncio.to_thread(p.read_text, encoding="utf-8", errors="ignore")
            lines = text.splitlines()[-int(n) :]
            return JSONResponse(
                {
                    "ok": True,
                    "data": {"kind": kind, "path": path_s, "lines": lines, "error": None},
                },
            )
        except Exception as e:  # noqa: BLE001
            return JSONResponse(
                {
                    "ok": True,
                    "data": {"kind": kind, "path": path_s, "lines": [], "error": str(e)},
                },
            )

    @router.get(f"{x}/ai-extension/ncm/status", include_in_schema=True)
    async def _ai_extension_ncm_status() -> JSONResponse:
        async def _load() -> dict[str, Any]:
            return await _ai_extension_http_json(method="GET", path="/ncm/login/status")

        d = await _cached_read(key="ai_extension_ncm_status", loader=_load, ttl_sec=3.0, stale_sec=30.0)
        return JSONResponse({"ok": True, "data": d})

    @router.post(f"{x}/ai-extension/ncm/send-sms", include_in_schema=True)
    async def _ai_extension_ncm_send_sms(
        body: _AiNcmSendSmsBody,
        token: str | None = Query(default=None),
        x_pallas_token: str | None = Header(default=None, alias="X-Pallas-Token"),
    ) -> JSONResponse:
        _check_pallas_write_token(plugin_config, x_pallas_token=x_pallas_token, token=token)
        d = await _ai_extension_http_json(
            method="POST",
            path="/ncm/login/cellphone/send-sms",
            body=body.model_dump(),
        )
        _drop_read_cache(("ai_extension_ncm_status",))
        return JSONResponse({"ok": True, "data": d})

    @router.post(f"{x}/ai-extension/ncm/verify-sms", include_in_schema=True)
    async def _ai_extension_ncm_verify_sms(
        body: _AiNcmVerifySmsBody,
        token: str | None = Query(default=None),
        x_pallas_token: str | None = Header(default=None, alias="X-Pallas-Token"),
    ) -> JSONResponse:
        _check_pallas_write_token(plugin_config, x_pallas_token=x_pallas_token, token=token)
        d = await _ai_extension_http_json(
            method="POST",
            path="/ncm/login/cellphone/verify-sms",
            body=body.model_dump(),
        )
        _drop_read_cache(("ai_extension_ncm_status",))
        return JSONResponse({"ok": True, "data": d})

    @router.post(f"{x}/ai-extension/ncm/logout", include_in_schema=True)
    async def _ai_extension_ncm_logout(
        token: str | None = Query(default=None),
        x_pallas_token: str | None = Header(default=None, alias="X-Pallas-Token"),
    ) -> JSONResponse:
        _check_pallas_write_token(plugin_config, x_pallas_token=x_pallas_token, token=token)
        d = await _ai_extension_http_json(method="POST", path="/ncm/login/logout", body={})
        _drop_read_cache(("ai_extension_ncm_status",))
        return JSONResponse({"ok": True, "data": d})

    @router.get(f"{x}/friend-requests", include_in_schema=True)
    async def _friend_requests(
        self_id: int | None = Query(default=None, description="仅查看指定 Bot QQ；不传则返回全部"),
        doubt: bool = Query(default=True, description="是否对在线 OneBot V11 号尝试拉取被过滤的可疑好友申请"),
    ) -> JSONResponse:
        """只读：request_handler 落盘的待处理好友申请 +（可选）协议侧可疑申请。"""

        async def _load() -> dict[str, Any]:
            sid = str(int(self_id)) if self_id is not None else None
            return await _friend_requests_overview(self_id=sid, include_doubt=bool(doubt))

        try:
            data = await _cached_read(
                key=f"friend_requests:{self_id}:{int(doubt)}",
                loader=_load,
                ttl_sec=1.0,
                stale_sec=12.0,
            )
        except Exception as e:  # noqa: BLE001
            logger.exception("Pallas-Bot 控制台: 读取好友申请概览失败")
            raise HTTPException(status_code=500, detail=str(e)) from e
        return JSONResponse({"ok": True, "data": data})

    @router.get(f"{x}/friend-list", include_in_schema=True)
    async def _friend_list(
        self_id: int = Query(..., description="Bot QQ（须当前在 NoneBot 已连接）"),
        limit: int = Query(default=800, ge=1, le=8000),
    ) -> JSONResponse:
        """只读：对在线 Bot 调用 OneBot `get_friend_list`（大列表时按 limit 截断并标记 truncated）。"""
        cache_key = f"friend_list:{int(self_id)}:{int(limit)}"

        async def _load() -> dict[str, Any]:
            target = str(int(self_id))
            bot = None
            conn_key = ""
            for key, b in get_bots().items():
                if str(getattr(b, "self_id", "") or "") == target:
                    bot = b
                    conn_key = str(key)
                    break
            if bot is None:
                raise HTTPException(status_code=404, detail="指定账号当前未连接")
            if not _is_onebot_v11_bot(bot):
                raise HTTPException(status_code=400, detail="当前连接不是 OneBot V11，无法拉取好友列表")

            friends, err, truncated = await _call_get_friend_list(bot, limit=int(limit))
            return {
                "self_id": target,
                "connection_key": conn_key,
                "adapter": _bot_adapter_label(bot),
                "friends": friends,
                "truncated": truncated,
                "limit": int(limit),
                "error": err,
            }

        try:
            payload = await _cached_read(key=cache_key, loader=_load, ttl_sec=2.5, stale_sec=25.0)
        except HTTPException:
            raise
        except Exception as e:  # noqa: BLE001
            logger.exception("Pallas-Bot 控制台: 拉取好友列表失败")
            raise HTTPException(status_code=500, detail=str(e)) from e
        return JSONResponse({"ok": True, "data": payload})

    @router.get(f"{x}/group-list", include_in_schema=True)
    async def _group_list(
        self_id: int = Query(..., description="Bot QQ（须当前在 NoneBot 已连接）"),
        limit: int = Query(default=1000, ge=1, le=10000),
    ) -> JSONResponse:
        """只读：对在线 Bot 调用 OneBot `get_group_list`（大列表时按 limit 截断并标记 truncated）。"""
        cache_key = f"group_list:{int(self_id)}:{int(limit)}"

        async def _load() -> dict[str, Any]:
            target = str(int(self_id))
            bot = None
            conn_key = ""
            for key, b in get_bots().items():
                if str(getattr(b, "self_id", "") or "") == target:
                    bot = b
                    conn_key = str(key)
                    break
            if bot is None:
                raise HTTPException(status_code=404, detail="指定账号当前未连接")
            if not _is_onebot_v11_bot(bot):
                raise HTTPException(status_code=400, detail="当前连接不是 OneBot V11，无法拉取群列表")

            groups, err, truncated = await _call_get_group_list(bot, limit=int(limit))
            return {
                "self_id": target,
                "connection_key": conn_key,
                "adapter": _bot_adapter_label(bot),
                "groups": groups,
                "truncated": truncated,
                "limit": int(limit),
                "error": err,
            }

        try:
            payload = await _cached_read(key=cache_key, loader=_load, ttl_sec=2.5, stale_sec=25.0)
        except HTTPException:
            raise
        except Exception as e:  # noqa: BLE001
            logger.exception("Pallas-Bot 控制台: 拉取群列表失败")
            raise HTTPException(status_code=500, detail=str(e)) from e
        return JSONResponse({"ok": True, "data": payload})

    @router.get(f"{x}/request-overview", include_in_schema=True)
    async def _request_overview() -> JSONResponse:
        async def _load() -> dict[str, Any]:
            friend = await _friend_requests_overview(self_id=None, include_doubt=True)
            group = _read_pending_group_requests_disk()
            by_self: dict[str, dict[str, Any]] = {}
            for row in friend.get("bots", []):
                sid = str(row.get("self_id") or "")
                if not sid:
                    continue
                by_self[sid] = {
                    "self_id": sid,
                    "online": bool(row.get("online")),
                    "adapter": str(row.get("adapter") or ""),
                    "connection_key": row.get("connection_key"),
                    "pending_friend_requests": row.get("pending_friend_requests") or [],
                    "doubt_friend_requests": row.get("doubt_friend_requests") or [],
                    "pending_group_requests": [],
                }
            for sid, mp in group.items():
                row = by_self.setdefault(
                    str(sid),
                    {
                        "self_id": str(sid),
                        "online": False,
                        "adapter": "",
                        "connection_key": None,
                        "pending_friend_requests": [],
                        "doubt_friend_requests": [],
                        "pending_group_requests": [],
                    },
                )
                vals = [v for v in mp.values() if isinstance(v, dict)]
                vals.sort(key=lambda v: int(v.get("group_id") or 0))
                row["pending_group_requests"] = vals
            rows = sorted(
                by_self.values(),
                key=lambda r: int(str(r["self_id"])) if str(r["self_id"]).isdigit() else 10**18,
            )
            return {"bots": rows}

        try:
            data = await _cached_read(key="request_overview", loader=_load, ttl_sec=1.2, stale_sec=15.0)
        except Exception as e:  # noqa: BLE001
            logger.exception("Pallas-Bot 控制台: 读取审批总览失败")
            raise HTTPException(status_code=500, detail=str(e)) from e
        return JSONResponse({"ok": True, "data": data})

    @router.post(f"{x}/request-actions", include_in_schema=True)
    async def _request_actions(
        body: _RequestActionBody,
        token: str | None = Query(default=None),
        x_pallas_token: str | None = Header(default=None, alias="X-Pallas-Token"),
    ) -> JSONResponse:
        _check_pallas_write_token(plugin_config, x_pallas_token=x_pallas_token, token=token)
        _, bot = _find_online_onebot_v11_bot(str(body.self_id))
        approve = body.action == "approve"
        if body.kind == "friend":
            if body.user_id is None:
                raise HTTPException(status_code=400, detail="friend 请求需要 user_id")
            uid = str(int(body.user_id))
            if body.source == "doubt":
                doubt = await _call_get_doubt_friends(bot)
                flag = next((str(x.get("flag") or "") for x in doubt if str(x.get("user_id")) == uid), "")
                if not flag:
                    raise HTTPException(status_code=404, detail="未找到可疑好友申请")
                await bot.call_api("set_doubt_friends_add_request", flag=flag, approve=approve)  # type: ignore[union-attr]
                _drop_read_cache(_CONSOLE_APPROVAL_RELATED_CACHE_PREFIXES)
                return JSONResponse({"ok": True, "data": {"handled": True}})
            pending = _read_pending_friend_requests_disk()
            by_bot = pending.get(str(body.self_id), {})
            flag = str(by_bot.get(uid) or "")
            if not flag:
                raise HTTPException(status_code=404, detail="未找到待处理好友申请")
            await bot.set_friend_add_request(flag=flag, approve=approve)  # type: ignore[union-attr]
            by_bot.pop(uid, None)
            pending[str(body.self_id)] = by_bot
            _save_pending_friend_requests_disk(pending)
            _drop_read_cache(_CONSOLE_APPROVAL_RELATED_CACHE_PREFIXES)
            return JSONResponse({"ok": True, "data": {"handled": True}})

        if body.group_id is None:
            raise HTTPException(status_code=400, detail="group 请求需要 group_id")
        pending_g = _read_pending_group_requests_disk()
        by_bot_g = pending_g.get(str(body.self_id), {})
        req = by_bot_g.get(str(int(body.group_id)))
        if not isinstance(req, dict):
            raise HTTPException(status_code=404, detail="未找到待处理群邀请")
        await bot.set_group_add_request(  # type: ignore[union-attr]
            flag=str(req.get("flag") or ""),
            sub_type=str(req.get("sub_type") or "invite"),
            approve=approve,
        )
        by_bot_g.pop(str(int(body.group_id)), None)
        pending_g[str(body.self_id)] = by_bot_g
        _save_pending_group_requests_disk(pending_g)
        _drop_read_cache(_CONSOLE_APPROVAL_RELATED_CACHE_PREFIXES)
        return JSONResponse({"ok": True, "data": {"handled": True}})

    @router.post(f"{x}/request-actions/batch", include_in_schema=True)
    async def _request_actions_batch(
        body: _RequestActionsBatchBody,
        token: str | None = Query(default=None),
        x_pallas_token: str | None = Header(default=None, alias="X-Pallas-Token"),
    ) -> JSONResponse:
        """批量处理好友/入群审批；单次写盘与缓存失效，减少控制台往返。"""
        _check_pallas_write_token(plugin_config, x_pallas_token=x_pallas_token, token=token)
        if not body.friends and not body.groups:
            raise HTTPException(status_code=400, detail="friends 与 groups 不能均为空")

        approve = body.action == "approve"
        friends_ok = 0
        friends_fail = 0
        friends_errors: list[dict[str, Any]] = []
        groups_ok = 0
        groups_fail = 0
        groups_errors: list[dict[str, Any]] = []

        pending_friend: dict[str, dict[str, str]] = {}
        if body.friends:
            pending_friend = _read_pending_friend_requests_disk()

        friends_by_sid: dict[str, list[_RequestBatchFriendRow]] = defaultdict(list)
        for it in body.friends:
            friends_by_sid[str(int(it.self_id))].append(it)

        for sid_str, items in friends_by_sid.items():
            try:
                _, bot = _find_online_onebot_v11_bot(sid_str)
            except HTTPException as e:
                detail = e.detail
                msg = detail if isinstance(detail, str) else str(detail)
                for it in items:
                    friends_fail += 1
                    friends_errors.append({
                        "self_id": int(sid_str),
                        "user_id": it.user_id,
                        "source": it.source,
                        "error": msg,
                    })
                continue

            if sid_str not in pending_friend:
                pending_friend[sid_str] = {}
            bot_pending = pending_friend[sid_str]

            for it in items:
                uid = str(int(it.user_id))
                try:
                    if it.source == "doubt":
                        doubt_rows = await _call_get_doubt_friends(bot)
                        flag = ""
                        for row in doubt_rows:
                            if not isinstance(row, dict):
                                continue
                            if str(row.get("user_id") or "") != uid:
                                continue
                            flag = str(row.get("flag") or "")
                            break
                        if not flag:
                            raise ValueError("未找到可疑好友申请")
                        await bot.call_api("set_doubt_friends_add_request", flag=flag, approve=approve)  # type: ignore[union-attr]
                    else:
                        flag = str(bot_pending.get(uid) or "")
                        if not flag:
                            raise ValueError("未找到待处理好友申请")
                        await bot.set_friend_add_request(flag=flag, approve=approve)  # type: ignore[union-attr]
                        bot_pending.pop(uid, None)
                    friends_ok += 1
                except Exception as e:  # noqa: BLE001
                    friends_fail += 1
                    friends_errors.append({
                        "self_id": int(sid_str),
                        "user_id": it.user_id,
                        "source": it.source,
                        "error": str(e),
                    })

            pending_friend[sid_str] = bot_pending

        if body.friends:
            _save_pending_friend_requests_disk(pending_friend)

        pending_group: dict[str, dict[str, dict[str, Any]]] = {}
        if body.groups:
            pending_group = _read_pending_group_requests_disk()

        groups_by_sid: dict[str, list[_RequestBatchGroupRow]] = defaultdict(list)
        for it in body.groups:
            groups_by_sid[str(int(it.self_id))].append(it)

        for sid_str, items in groups_by_sid.items():
            try:
                _, bot = _find_online_onebot_v11_bot(sid_str)
            except HTTPException as e:
                detail = e.detail
                msg = detail if isinstance(detail, str) else str(detail)
                for it in items:
                    groups_fail += 1
                    groups_errors.append({
                        "self_id": int(sid_str),
                        "user_id": it.user_id,
                        "group_id": it.group_id,
                        "error": msg,
                    })
                continue

            if sid_str not in pending_group:
                pending_group[sid_str] = {}
            bot_grp = pending_group[sid_str]

            for it in items:
                gkey = str(int(it.group_id))
                try:
                    req = bot_grp.get(gkey)
                    if not isinstance(req, dict):
                        raise ValueError("未找到待处理群邀请")
                    await bot.set_group_add_request(  # type: ignore[union-attr]
                        flag=str(req.get("flag") or ""),
                        sub_type=str(req.get("sub_type") or "invite"),
                        approve=approve,
                    )
                    bot_grp.pop(gkey, None)
                    groups_ok += 1
                except Exception as e:  # noqa: BLE001
                    groups_fail += 1
                    groups_errors.append({
                        "self_id": int(sid_str),
                        "user_id": it.user_id,
                        "group_id": it.group_id,
                        "error": str(e),
                    })

            pending_group[sid_str] = bot_grp

        if body.groups:
            _save_pending_group_requests_disk(pending_group)
        _drop_read_cache(_CONSOLE_APPROVAL_RELATED_CACHE_PREFIXES)

        return JSONResponse({
            "ok": True,
            "data": {
                "friends_ok": friends_ok,
                "friends_fail": friends_fail,
                "friends_errors": friends_errors,
                "groups_ok": groups_ok,
                "groups_fail": groups_fail,
                "groups_errors": groups_errors,
            },
        })

    @router.get(f"{x}/update/check", include_in_schema=True)
    async def _update_check() -> JSONResponse:
        from src.common.utils.format_exception import format_exception_for_log
        from src.common.utils.github_release import release_tags_equivalent

        from .manager import fetch_latest_webui_release, get_installed_webui_version

        repo = str(getattr(plugin_config, "pallas_webui_dist_zip_repo", "") or "PallasBot/Pallas-Bot-WebUI")
        asset = str(getattr(plugin_config, "pallas_webui_dist_zip_asset", "") or "dist.zip")
        github_token = str(getattr(plugin_config, "pallas_protocol_github_token", "") or "").strip()
        cache_key = f"update_check_webui:{repo}:{asset}:{bool(github_token)}"

        async def _load() -> dict[str, Any]:
            installed = get_installed_webui_version()
            current_tag = str(installed.get("tag", "") or "").strip()
            try:
                latest = await fetch_latest_webui_release(repo, token=github_token, asset_name=asset)
                latest_tag = str(latest.get("tag", "") or "").strip()
                release_url = str(latest.get("html_url", "") or "").strip()
                asset_url = str(latest.get("asset_url", "") or "").strip()
            except Exception as e:  # noqa: BLE001
                err_msg = format_exception_for_log(e)
                logger.warning("Pallas-Bot 控制台: WebUI 更新检查失败（GitHub），repo={} err={}", repo, err_msg)
                return {
                    "current_tag": current_tag,
                    "latest_tag": None,
                    "has_update": False,
                    "release_url": "",
                    "asset_url": "",
                    "release_notes": "",
                    "error": err_msg,
                    "checked_at": time.time(),
                }
            has_update = bool(latest_tag and not release_tags_equivalent(current_tag, latest_tag))
            notes_raw = str(latest.get("body", "") or "").strip()
            notes_max = 40000
            release_notes = (
                notes_raw
                if len(notes_raw) <= notes_max
                else f"{notes_raw[:notes_max].rstrip()}\n\n…（已截断，完整内容见 Release 页面）"
            )
            return {
                "current_tag": current_tag,
                "latest_tag": latest_tag,
                "has_update": has_update,
                "release_url": release_url,
                "asset_url": asset_url,
                "release_notes": release_notes,
                "error": None,
                "checked_at": time.time(),
            }

        data = await _cached_read(key=cache_key, loader=_load, ttl_sec=120.0, stale_sec=900.0)
        return JSONResponse({"ok": True, "data": data})

    @router.get(f"{x}/update/bot/check", include_in_schema=True)
    async def _bot_update_check() -> JSONResponse:
        from src.common.utils.format_exception import format_exception_for_log

        from .manager import bot_has_release_update, fetch_latest_bot_release, get_bot_current_version

        github_token = str(getattr(plugin_config, "pallas_protocol_github_token", "") or "").strip()
        cache_key = f"update_check_bot:{bool(github_token)}"

        async def _load() -> dict[str, Any]:
            current = get_bot_current_version()
            current_tag = current.get("tag", "")
            current_commit = current.get("commit", "")
            try:
                latest = await fetch_latest_bot_release("PallasBot/Pallas-Bot", token=github_token)
                latest_tag = str(latest.get("tag", "") or "").strip()
                release_url = str(latest.get("html_url", "") or "").strip()
            except Exception as e:  # noqa: BLE001
                err_msg = format_exception_for_log(e)
                logger.warning("Pallas-Bot 控制台: Bot 版本更新检查失败（GitHub） err={}", err_msg)
                return {
                    "current_tag": current_tag,
                    "current_commit": current_commit,
                    "latest_tag": None,
                    "has_update": False,
                    "release_url": "",
                    "release_notes": "",
                    "error": err_msg,
                    "checked_at": time.time(),
                }
            has_update = bot_has_release_update(
                latest_tag=latest_tag,
                current_tag=str(current_tag or ""),
                current_commit=str(current_commit or ""),
            )
            notes_raw = str(latest.get("body", "") or "").strip()
            notes_max = 40000
            release_notes = (
                notes_raw
                if len(notes_raw) <= notes_max
                else f"{notes_raw[:notes_max].rstrip()}\n\n…（已截断，完整内容见 Release 页面）"
            )
            return {
                "current_tag": current_tag,
                "current_commit": current_commit,
                "latest_tag": latest_tag,
                "has_update": has_update,
                "release_url": release_url,
                "release_notes": release_notes,
                "error": None,
                "checked_at": time.time(),
            }

        data = await _cached_read(key=cache_key, loader=_load, ttl_sec=120.0, stale_sec=900.0)
        return JSONResponse({"ok": True, "data": data})

    @router.post(f"{x}/update/bot/apply", include_in_schema=True)
    async def _bot_update_apply(
        token: str | None = Query(default=None),
        x_pallas_token: str | None = Header(default=None, alias="X-Pallas-Token"),
    ) -> JSONResponse:
        _check_pallas_write_token(plugin_config, x_pallas_token=x_pallas_token, token=token)
        from src.common.utils.format_exception import format_exception_for_log

        from .manager import BotGitUpdateError, apply_bot_repository_update

        github_token = str(getattr(plugin_config, "pallas_protocol_github_token", "") or "").strip()
        try:
            logger.info("Pallas-Bot 控制台: Bot 仓库在线更新（git）请求已接受")
            data = await apply_bot_repository_update(
                github_token=github_token,
                repo="PallasBot/Pallas-Bot",
            )
            _drop_read_cache(("update_check_bot:",))
            return JSONResponse({"ok": True, "data": data})
        except BotGitUpdateError as e:
            raise HTTPException(status_code=e.status_code, detail=e.detail) from e
        except HTTPException:
            raise
        except Exception as e:  # noqa: BLE001
            logger.exception("Pallas-Bot 控制台: Bot 仓库更新失败")
            raise HTTPException(status_code=500, detail=format_exception_for_log(e)) from e

    @router.post(f"{x}/update/apply", include_in_schema=True)
    async def _update_apply(
        token: str | None = Query(default=None),
        x_pallas_token: str | None = Header(default=None, alias="X-Pallas-Token"),
    ) -> JSONResponse:
        _check_pallas_write_token(plugin_config, x_pallas_token=x_pallas_token, token=token)
        from src.common.utils.format_exception import format_exception_for_log

        from .manager import (
            download_and_extract_dist_zip,
            fetch_latest_webui_release,
            get_webui_dist_version,
            resolve_github_release_asset_urls,
            save_installed_webui_version,
            webui_public_path,
        )

        repo = str(getattr(plugin_config, "pallas_webui_dist_zip_repo", "") or "PallasBot/Pallas-Bot-WebUI")
        asset = str(getattr(plugin_config, "pallas_webui_dist_zip_asset", "") or "dist.zip")
        tag = str(getattr(plugin_config, "pallas_webui_dist_zip_tag", "") or "")
        github_token = str(getattr(plugin_config, "pallas_protocol_github_token", "") or "").strip()
        public = webui_public_path()
        try:
            logger.info(
                "Pallas-Bot 控制台: WebUI 在线更新开始 repo={} asset={} tag={}",
                repo,
                asset,
                tag or "(latest)",
            )
            url_candidates = await resolve_github_release_asset_urls(repo, asset, tag, token=github_token)
            if not url_candidates:
                logger.warning("Pallas-Bot 控制台: WebUI 更新未得到任何下载 URL（resolve 为空）")
                raise ValueError("未找到可用的下载地址")
            logger.info("Pallas-Bot 控制台: WebUI 更新候选地址 {} 条", len(url_candidates))
            errors: list[str] = []
            succeeded_url = ""
            for i, candidate in enumerate(url_candidates, start=1):
                short = candidate if len(candidate) <= 160 else candidate[:157] + "..."
                logger.info("Pallas-Bot 控制台: WebUI 更新尝试 {}/{} {}", i, len(url_candidates), short)
                try:
                    await download_and_extract_dist_zip(public, candidate)
                    succeeded_url = candidate
                    errors.clear()
                    break
                except Exception as e:  # noqa: BLE001
                    err_msg = format_exception_for_log(e)
                    errors.append(f"{candidate} -> {err_msg}")
                    logger.warning("Pallas-Bot 控制台: WebUI 下载/解压失败 {}", err_msg)
            if errors:
                raise ValueError("下载失败: " + " | ".join(errors))
            try:
                info = await fetch_latest_webui_release(repo, token=github_token, asset_name=asset)
                new_tag = str(info.get("tag", "") or tag).strip()
            except Exception as e:  # noqa: BLE001
                logger.warning(
                    "Pallas-Bot 控制台: 获取 WebUI release 元数据失败，使用配置 tag={} err={}",
                    tag or "(空)",
                    format_exception_for_log(e),
                )
                new_tag = tag
            save_installed_webui_version(new_tag, succeeded_url)
            # 更新成功后同步刷新内存里的 console 版本，避免必须重启后前端才显示新版本。
            try:
                dist_ver = get_webui_dist_version()
            except Exception:  # noqa: BLE001
                dist_ver = ""
            effective_version = (dist_ver or "").strip() or new_tag or "unknown"
            set_console_meta({**_CONSOLE_EXTRA, "version": effective_version})
            logger.info("Pallas-Bot 控制台: WebUI 已更新至 {}（发布 tag: {}）", effective_version, new_tag)
            _drop_read_cache(("update_check_webui:",))
            return JSONResponse({
                "ok": True,
                "data": {
                    "tag": new_tag,
                    "version": effective_version,
                    "message": "更新成功",
                },
            })
        except HTTPException:
            raise
        except Exception as e:  # noqa: BLE001
            logger.exception("Pallas-Bot 控制台: WebUI 更新失败")
            raise HTTPException(status_code=500, detail=format_exception_for_log(e)) from e

    @router.post(f"{x}/security/console-login", include_in_schema=False)
    async def _security_console_login(
        body: _ChangeConsoleLoginBody,
        token: str | None = Query(default=None),
        x_pallas_token: str | None = Header(default=None, alias="X-Pallas-Token"),
    ) -> JSONResponse:
        _check_pallas_write_token(plugin_config, x_pallas_token=x_pallas_token, token=token)
        try:
            set_shared_console_login_token(body.new_password)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e
        return JSONResponse({"ok": True, "data": {"message": "已保存"}})

    if not getattr(app.state, "_pallas_ext_read_cache_inv_hook", False):
        register_console_session_invalidation_hook(clear_extended_read_cache)
        app.state._pallas_ext_read_cache_inv_hook = True

    app.include_router(router_pub)
    app.include_router(router)

    try:
        from nonebot_plugin_apscheduler import scheduler
    except ImportError:
        logger.warning("Pallas-Bot 控制台: 未安装 nonebot_plugin_apscheduler，跳过控制台异常记录定时清理")
    else:
        _matcher_cleanup_job_id = "pallas_webui_matcher_error_log_cleanup"
        if scheduler.get_job(_matcher_cleanup_job_id):
            scheduler.remove_job(_matcher_cleanup_job_id)
        scheduler.add_job(
            _scheduled_cleanup_matcher_error_logs,
            trigger="cron",
            hour=4,
            minute=0,
            id=_matcher_cleanup_job_id,
            replace_existing=True,
            coalesce=True,
            max_instances=1,
            misfire_grace_time=3600,
        )
        _daily_flush_id = "pallas_webui_console_daily_stats_flush"
        if scheduler.get_job(_daily_flush_id):
            scheduler.remove_job(_daily_flush_id)
        scheduler.add_job(
            _flush_today_console_daily_stats_disk,
            trigger="interval",
            minutes=2,
            id=_daily_flush_id,
            replace_existing=True,
            coalesce=True,
            max_instances=1,
        )
