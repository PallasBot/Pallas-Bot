"""控制台扩展 JSON：系统/插件/连接/日志，以及实例、库、Bot/群配置等只读与受控写接口。"""

from __future__ import annotations

import asyncio
import importlib
import json
import platform
import re
import shutil
import time
import typing
from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter, Header, HTTPException, Query
from fastapi.responses import JSONResponse
from nonebot import get_bots, get_driver, get_loaded_plugins, get_plugin_config, logger
from nonebot.adapters import Bot as BaseBot  # noqa: TC002
from nonebot.adapters import Event  # noqa: TC002
from pydantic import BaseModel, ConfigDict, Field
from pydantic_core import PydanticUndefined

if typing.TYPE_CHECKING:
    from .config import Config

_CONSOLE_EXTRA: dict[str, Any] = {}
_INIT_LOG_SINK = False
_READ_CACHE: dict[str, dict[str, Any]] = {}
_MSG_STATS: dict[str, dict[str, int]] = {}  # {self_id: {"sent": N, "received": N}}
_MSG_TRACKING_INIT = False


def set_console_meta(d: dict[str, Any] | None) -> None:
    """由 __init__ 在启动时注入 static_root、http_base 等，供 /system 与前端展示。"""
    _CONSOLE_EXTRA.clear()
    if d:
        _CONSOLE_EXTRA.update(d)


def _ensure_log_sink() -> None:
    global _INIT_LOG_SINK
    if _INIT_LOG_SINK:
        return
    from src.common.web import install_nonebot_log_sink

    install_nonebot_log_sink()
    _INIT_LOG_SINK = True
    logger.info("Pallas 控制台: 已接入 NoneBot 日志环（/pallas/api/logs）")


async def _cached_read(
    *,
    key: str,
    loader: typing.Callable[[], typing.Awaitable[Any]],
    ttl_sec: float = 1.0,
    stale_sec: float = 20.0,
) -> Any:
    """读取接口防抖：短 TTL 复用；失败时回退最近成功快照，降低前端空白概率。"""
    now = time.monotonic()
    hit = _READ_CACHE.get(key)
    if hit and now < float(hit["exp"]):
        return hit["data"]
    try:
        data = await loader()
    except Exception:
        if hit and now < float(hit["stale_exp"]):
            logger.warning("Pallas 控制台: 使用缓存兜底 key=%s", key)
            return hit["data"]
        raise
    _READ_CACHE[key] = {
        "data": data,
        "exp": now + max(0.05, ttl_sec),
        "stale_exp": now + max(ttl_sec, stale_sec),
    }
    return data


def _drop_read_cache(prefixes: tuple[str, ...]) -> None:
    if not _READ_CACHE:
        return
    for k in [k for k in _READ_CACHE if any(k.startswith(p) for p in prefixes)]:
        _READ_CACHE.pop(k, None)


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
        from src.plugins.help.config import Config as HelpConfig
        from src.plugins.help.visibility import load_help_hidden_plugins

        cfg = get_plugin_config(HelpConfig)
        ignored = {str(x).strip() for x in list(getattr(cfg, "ignored_plugins", []) or []) if str(x).strip()}
        hidden = {str(x).strip() for x in load_help_hidden_plugins() if str(x).strip()}
    except Exception:
        pass
    return ignored, hidden


def _list_plugins_dict() -> list[dict[str, Any]]:
    ignored, hidden = _help_menu_control()
    out: list[dict[str, Any]] = []
    for p in get_loaded_plugins():
        if not p.name:
            continue
        mod = getattr(p, "module", None)
        module_name = getattr(mod, "__name__", "") if mod is not None else ""
        if not module_name:
            module_name = str(getattr(p, "module_name", "") or "")
        out.append({
            "name": p.name,
            "module": module_name,
            "metadata": _metadata_to_dict(p.metadata),
            "help_visible": p.name not in ignored and p.name not in hidden,
            "help_ignored": p.name in ignored,
            "help_hidden": p.name in hidden,
        })
    out.sort(key=lambda x: x["name"] or "")
    return out


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


def _plugin_env_path() -> Path:
    return Path(__file__).resolve().parents[3] / ".env"


def _find_loaded_plugin(plugin_name: str):
    target = (plugin_name or "").strip()
    for p in get_loaded_plugins():
        if str(getattr(p, "name", "") or "").strip() == target:
            return p
    return None


def _plugin_module_name(p: Any) -> str:
    mod = getattr(p, "module", None)
    module_name = getattr(mod, "__name__", "") if mod is not None else ""
    if not module_name:
        module_name = str(getattr(p, "module_name", "") or "")
    return module_name.strip()


def _plugin_config_model_by_name(plugin_name: str):
    p = _find_loaded_plugin(plugin_name)
    if p is None:
        raise ValueError(f"未找到插件: {plugin_name}")
    module_name = _plugin_module_name(p)
    if not module_name:
        raise ValueError(f"插件模块名为空: {plugin_name}")
    cfg_mod_name = module_name if module_name.endswith(".config") else f"{module_name}.config"
    try:
        cfg_mod = importlib.import_module(cfg_mod_name)
    except Exception as e:  # noqa: BLE001
        raise ValueError(f"插件缺少 config.py: {plugin_name}") from e
    cfg_cls = getattr(cfg_mod, "Config", None)
    if cfg_cls is None or not isinstance(cfg_cls, type) or not issubclass(cfg_cls, BaseModel):
        raise ValueError(f"插件 config.py 未定义 Config(BaseModel): {plugin_name}")
    return p, module_name, cfg_cls


def _field_kind_from_annotation(ann: Any) -> str:
    text = str(ann).lower()
    if "list" in text or "dict" in text or "set" in text or "tuple" in text:
        return "json"
    if "bool" in text:
        return "bool"
    if "int" in text:
        return "int"
    if "float" in text:
        return "float"
    return "string"


def _plugin_config_payload(plugin_name: str) -> dict[str, Any]:
    p, module_name, cfg_cls = _plugin_config_model_by_name(plugin_name)
    cfg_obj = get_plugin_config(cfg_cls)
    fields: list[dict[str, Any]] = []
    for key, f in cfg_cls.model_fields.items():
        cur = getattr(cfg_obj, key, f.default)
        default_value = None if f.default is PydanticUndefined else f.default
        fields.append({
            "name": key,
            "kind": _field_kind_from_annotation(f.annotation),
            "required": bool(f.is_required()),
            "description": str(f.description or ""),
            "env_key": key.upper(),
            "default": _jsonable_value(default_value),
            "current": _jsonable_value(cur),
        })
    return {
        "plugin": str(getattr(p, "name", "") or plugin_name),
        "module": module_name,
        "fields": fields,
    }


def _to_env_value(v: Any) -> str:
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (dict, list)):
        return json.dumps(v, ensure_ascii=False)
    if v is None:
        return ""
    return str(v)


def _upsert_env_items(items: dict[str, str]) -> None:
    path = _plugin_env_path()
    if path.exists():
        lines = path.read_text(encoding="utf-8").splitlines()
    else:
        lines = []
    remained = set(items.keys())
    out: list[str] = []
    for line in lines:
        replaced = False
        for k, v in items.items():
            # 同名键若存在注释行，直接改写并取消注释
            if re.match(rf"^\s*#?\s*{re.escape(k)}\s*=", line):
                out.append(f"{k}={v}")
                remained.discard(k)
                replaced = True
                break
        if not replaced:
            out.append(line)
    if remained:
        if out and out[-1].strip() != "":
            out.append("")
        out.extend(f"{k}={items[k]}" for k in sorted(remained))
    path.write_text("\n".join(out) + "\n", encoding="utf-8")


def _list_bots_dict() -> list[dict[str, Any]]:
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
    import json

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
    import json

    from src.common.paths import plugin_data_dir

    path = plugin_data_dir("request_handler") / "pending_friend_requests.json"
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _read_pending_group_requests_disk() -> dict[str, dict[str, dict[str, Any]]]:
    """与 request_handler 插件写入的 JSON 结构一致：{ bot_id: { group_id: request } }。"""
    import json

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
    import json

    from src.common.paths import plugin_data_dir

    path = plugin_data_dir("request_handler") / "pending_group_requests.json"
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _ai_extension_config_path():
    from src.common.paths import plugin_data_dir

    return plugin_data_dir("pallas_webui") / "ai_extension.json"


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
    uvicorn_log_file = str(d.get("uvicorn_log_file", "")).strip() or str(default_ai_root / "logs" / "app.log")
    celery_log_file = str(d.get("celery_log_file", "")).strip() or str(default_ai_root / "logs" / "app.log")
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
    import json

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
    import json

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
    if not isinstance(item, dict):
        return None
    gid = item.get("group_id")
    try:
        group_id = int(gid)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    if group_id <= 0:
        return None
    return {
        "group_id": group_id,
        "group_name": str(item.get("group_name") or ""),
        "member_count": int(item.get("member_count") or 0),  # type: ignore[arg-type]
        "max_member_count": int(item.get("max_member_count") or 0),  # type: ignore[arg-type]
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
    else:
        groups_raw = []
    out: list[dict[str, Any]] = []
    for it in groups_raw:
        row = _normalize_group_list_item(it)
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


async def _call_get_doubt_friends(bot: object) -> list[dict[str, Any]]:
    try:
        raw = await bot.call_api("get_doubt_friends_add_request", count=50)  # type: ignore[union-attr]
    except Exception:  # noqa: BLE001
        return []
    if not isinstance(raw, list):
        return []
    out: list[dict[str, Any]] = []
    for x in raw:
        if not isinstance(x, dict) or "user_id" not in x:
            continue
        try:
            uid = int(x["user_id"])
        except (TypeError, ValueError):
            continue
        out.append({"user_id": uid, "flag": str(x.get("flag", ""))})
    return out


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


def _init_message_tracking() -> None:
    """注册 NoneBot2 钩子，在内存中统计每个 Bot 的收发消息数。
    - 收消息：event_preprocessor，事件类型为 "message" 时计数
    - 发消息：Bot.on_called_api，send_msg / send_group_msg / send_private_msg 成功时计数
    """
    global _MSG_TRACKING_INIT
    if _MSG_TRACKING_INIT:
        return
    _MSG_TRACKING_INIT = True

    from nonebot.adapters import Bot as BaseBot
    from nonebot.message import event_preprocessor

    _send_apis = frozenset({"send_msg", "send_group_msg", "send_private_msg", "send_message"})

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
                _MSG_STATS.setdefault(sid, {"sent": 0, "received": 0})["sent"] += 1

    @event_preprocessor
    async def _count_received(bot: BaseBot, event: Event) -> None:
        try:
            if event.get_type() == "message":
                sid = str(getattr(bot, "self_id", "") or "").strip()
                if sid:
                    _MSG_STATS.setdefault(sid, {"sent": 0, "received": 0})["received"] += 1
        except Exception:  # noqa: BLE001
            pass


async def _message_stats_overview(*, self_id: str | None) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    total_sent = 0
    total_received = 0
    for key, bot in get_bots().items():
        sid = str(getattr(bot, "self_id", "") or "").strip()
        if not sid:
            continue
        if self_id and sid != str(self_id).strip():
            continue
        if not _is_onebot_v11_bot(bot):
            continue

        # 优先使用内存计数器（兼容 NapCat 等 stat:{} 为空的实现）
        mem = _MSG_STATS.get(sid, {"sent": 0, "received": 0})
        sent = mem["sent"]
        received = mem["received"]

        # 同时尝试 get_status（go-cqhttp 等会返回真实统计），取较大值
        try:
            status_raw = await bot.call_api("get_status")  # type: ignore[union-attr]
            api_stats = _extract_message_stats(status_raw)
            sent = max(sent, api_stats["sent"])
            received = max(received, api_stats["received"])
        except Exception:  # noqa: BLE001
            pass

        total_sent += sent
        total_received += received
        rows.append({
            "self_id": sid,
            "connection_key": str(key),
            "sent": sent,
            "received": received,
        })
    return {"total_sent": total_sent, "total_received": total_received, "bots": rows}


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
            logger.debug("Pallas 控制台: get_login_info 失败 key=%s self_id=%s", key, self_id)
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
    return {
        "nonebot2_driver": {
            "host": host_s,
            "port": port_s,
        },
        "superuser_count": n_sup,
        "server_time": time.time(),
        "plugin_count": len(_list_plugins_dict()),
        "bot_count": len(get_bots()),
        "console": dict(_CONSOLE_EXTRA),
        "runtime": _runtime_metrics(),
    }


def _runtime_metrics() -> dict[str, Any]:
    cpu_percent: float | None = None
    mem: dict[str, Any] = {"total": None, "used": None, "percent": None}
    try:
        import psutil  # type: ignore

        cpu_percent = float(psutil.cpu_percent(interval=0.0))
        vm = psutil.virtual_memory()
        mem = {
            "total": int(getattr(vm, "total", 0) or 0),
            "used": int(getattr(vm, "used", 0) or 0),
            "percent": float(getattr(vm, "percent", 0.0) or 0.0),
        }
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

    return {
        "platform": platform.platform(),
        "python": platform.python_version(),
        "cpu_percent": cpu_percent,
        "memory": mem,
        "disk": disk,
        "gpu": _gpu_metrics(),
    }


def _check_pallas_write_token(
    plugin_config: Any,
    *,
    x_pallas_token: str | None,
    token: str | None,
) -> None:
    need = (getattr(plugin_config, "pallas_webui_api_token", None) or "").strip()
    if not need:
        return
    if (x_pallas_token or token or "").strip() != need:
        raise HTTPException(status_code=401, detail="Invalid token")


def _require_pallas_token_configured(
    plugin_config: Any,
    *,
    x_pallas_token: str | None,
    token: str | None,
) -> None:
    """数据库管道等敏感能力：未配置 token 时直接拒绝，避免匿名滥用。"""
    need = (getattr(plugin_config, "pallas_webui_api_token", None) or "").strip()
    if not need:
        raise HTTPException(
            status_code=403,
            detail="请先在环境变量中配置 pallas_webui_api_token，并在控制台设置页填入后再试",
        )
    if (x_pallas_token or token or "").strip() != need:
        raise HTTPException(status_code=401, detail="Invalid token")


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


class _RequestActionBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    self_id: int = Field(ge=1)
    kind: Literal["friend", "group"]
    action: Literal["approve", "reject"] = "approve"
    source: Literal["pending", "doubt"] = "pending"
    user_id: int | None = Field(default=None, ge=1)
    group_id: int | None = Field(default=None, ge=1)


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
        else:
            fields[field_name] = raw
    await repo.upsert_fields(group_id, fields)
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
        got = await _get_db_table_row_public("bot_config", int(row_id))
        if got is None:
            raise ValueError("upsert 后回读失败")
        return got
    if t == "group_config":
        repo = make_group_config_repository()
        allowed = {"disabled_plugins", "roulette_mode", "banned", "sing_progress"}
        for k in payload:
            if k not in allowed:
                raise ValueError(f"group_config 不允许字段: {k}")
        await repo.get_or_create(int(row_id), disabled_plugins=[])
        for k, v in payload.items():
            await repo.upsert_field(int(row_id), k, v)
        await repo.invalidate_cache()
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
    _init_message_tracking()
    x = (api_base or "/pallas/api").strip()
    if not x.startswith("/"):
        x = "/" + x
    x = x.rstrip("/")

    router = APIRouter(tags=["Pallas 控制台"])

    @router.get(f"{x}/system", include_in_schema=True)
    async def _system() -> JSONResponse:
        async def _load() -> dict[str, Any]:
            return _system_dict()

        data = await _cached_read(key="system", loader=_load, ttl_sec=0.8, stale_sec=8.0)
        return JSONResponse({"ok": True, "data": data})

    @router.get(f"{x}/message-stats", include_in_schema=True)
    async def _message_stats(
        self_id: int | None = Query(default=None, ge=1),
    ) -> JSONResponse:
        async def _load() -> dict[str, Any]:
            return await _message_stats_overview(self_id=str(self_id) if self_id is not None else None)

        key = f"message-stats:{self_id or 'all'}"
        data = await _cached_read(key=key, loader=_load, ttl_sec=2.0, stale_sec=10.0)
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
            data = _plugin_config_payload(plugin_name)
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
            _, _, cfg_cls = _plugin_config_model_by_name(plugin_name)
            current = get_plugin_config(cfg_cls).model_dump(mode="python")
            patch = dict(body.values or {})
            allowed = set(cfg_cls.model_fields.keys())
            for k in patch:
                if k not in allowed:
                    raise ValueError(f"未知配置项: {k}")
            merged = {**current, **patch}
            validated = cfg_cls(**merged).model_dump(mode="python")
            env_items = {str(k).upper(): _to_env_value(validated[k]) for k in patch}
            _upsert_env_items(env_items)
            data = _plugin_config_payload(plugin_name)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e
        except Exception as e:  # noqa: BLE001
            raise HTTPException(status_code=500, detail=str(e)) from e
        return JSONResponse({"ok": True, "data": data})

    @router.get(f"{x}/bots", include_in_schema=True)
    async def _bots() -> JSONResponse:
        async def _load() -> list[dict[str, Any]]:
            return _list_bots_dict()

        data = await _cached_read(key="bots", loader=_load, ttl_sec=0.9, stale_sec=15.0)
        return JSONResponse({"ok": True, "data": data})

    @router.get(f"{x}/logs", include_in_schema=True)
    async def _logs(
        n: int = Query(default=200, ge=1, le=plugin_config.pallas_webui_log_lines_max),
    ) -> JSONResponse:
        _ensure_log_sink()
        from src.common.web import tail_nonebot_log_lines

        return JSONResponse({
            "ok": True,
            "data": {
                "lines": tail_nonebot_log_lines(n),
                "max": plugin_config.pallas_webui_log_lines_max,
            },
        })

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
            logger.exception("Pallas 控制台: 数据库概览失败")
            raise HTTPException(status_code=500, detail=str(e)) from e
        return JSONResponse({"ok": True, "data": data})

    @router.post(f"{x}/db/mongodb/aggregate", include_in_schema=True)
    async def _db_mongo_aggregate(
        body: _MongoAggregateBody,
        token: str | None = Query(default=None),
        x_pallas_token: str | None = Header(default=None, alias="X-Pallas-Token"),
    ) -> JSONResponse:
        """受限 MongoDB aggregate（只读阶段白名单 + 强制结果上限）；须配置并携带 pallas_webui_api_token。"""
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
            logger.exception("Pallas 控制台: Mongo aggregate 失败")
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
            logger.exception("Pallas 控制台: 读取表行失败")
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
            logger.exception("Pallas 控制台: 写入表行失败")
            raise HTTPException(status_code=500, detail=str(e)) from e
        _drop_read_cache(("db_overview", "bot_configs_list", "group_configs_list", "instances"))
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
            logger.exception("Pallas 控制台: 删除表行失败")
            raise HTTPException(status_code=500, detail=str(e)) from e
        _drop_read_cache(("db_overview", "bot_configs_list", "group_configs_list", "instances"))
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
            logger.exception("Pallas 控制台: 加载实例视图失败")
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
            logger.exception("Pallas 控制台: 更新 Bot 配置失败")
            raise HTTPException(status_code=500, detail=str(e)) from e
        _drop_read_cache(("instances", "bot_configs_list", "db_overview"))
        return JSONResponse({"ok": True, "data": data})

    @router.get(f"{x}/group-configs", include_in_schema=True)
    async def _group_configs_list(
        limit: int = Query(default=1000, ge=1, le=10_000),
    ) -> JSONResponse:
        from src.common.db.pallas_console_data import list_group_configs_public

        key = f"group_configs_list:{int(limit)}"

        async def _load() -> list[dict[str, Any]]:
            return await list_group_configs_public(limit)

        try:
            rows = await _cached_read(key=key, loader=_load, ttl_sec=1.0, stale_sec=20.0)
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
        doc = await repo.get(group_id, ignore_cache=True)
        if doc is None:
            raise HTTPException(status_code=404, detail="未找到该群配置")
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
            logger.exception("Pallas 控制台: 更新群配置失败")
            raise HTTPException(status_code=500, detail=str(e)) from e
        _drop_read_cache(("group_configs_list", "db_overview"))
        return JSONResponse({"ok": True, "data": data})

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
            logger.exception("Pallas 控制台: 更新 User 配置失败")
            raise HTTPException(status_code=500, detail=str(e)) from e
        _drop_read_cache(("db_overview",))
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
        import json
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
        d = await _ai_extension_http_json(method="GET", path="/ncm/login/status")
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
        return JSONResponse({"ok": True, "data": d})

    @router.post(f"{x}/ai-extension/ncm/logout", include_in_schema=True)
    async def _ai_extension_ncm_logout(
        token: str | None = Query(default=None),
        x_pallas_token: str | None = Header(default=None, alias="X-Pallas-Token"),
    ) -> JSONResponse:
        _check_pallas_write_token(plugin_config, x_pallas_token=x_pallas_token, token=token)
        d = await _ai_extension_http_json(method="POST", path="/ncm/login/logout", body={})
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
            logger.exception("Pallas 控制台: 读取好友申请概览失败")
            raise HTTPException(status_code=500, detail=str(e)) from e
        return JSONResponse({"ok": True, "data": data})

    @router.get(f"{x}/friend-list", include_in_schema=True)
    async def _friend_list(
        self_id: int = Query(..., description="Bot QQ（须当前在 NoneBot 已连接）"),
        limit: int = Query(default=800, ge=1, le=8000),
    ) -> JSONResponse:
        """只读：对在线 Bot 调用 OneBot `get_friend_list`（大列表时按 limit 截断并标记 truncated）。"""
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
        payload: dict[str, Any] = {
            "self_id": target,
            "connection_key": conn_key,
            "adapter": _bot_adapter_label(bot),
            "friends": friends,
            "truncated": truncated,
            "limit": int(limit),
            "error": err,
        }
        return JSONResponse({"ok": True, "data": payload})

    @router.get(f"{x}/group-list", include_in_schema=True)
    async def _group_list(
        self_id: int = Query(..., description="Bot QQ（须当前在 NoneBot 已连接）"),
        limit: int = Query(default=1000, ge=1, le=10000),
    ) -> JSONResponse:
        """只读：对在线 Bot 调用 OneBot `get_group_list`（大列表时按 limit 截断并标记 truncated）。"""
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
        payload: dict[str, Any] = {
            "self_id": target,
            "connection_key": conn_key,
            "adapter": _bot_adapter_label(bot),
            "groups": groups,
            "truncated": truncated,
            "limit": int(limit),
            "error": err,
        }
        return JSONResponse({"ok": True, "data": payload})

    @router.get(f"{x}/request-overview", include_in_schema=True)
    async def _request_overview() -> JSONResponse:
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
        return JSONResponse({"ok": True, "data": {"bots": rows}})

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
                _drop_read_cache(("friend_requests",))
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
            _drop_read_cache(("friend_requests",))
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
        _drop_read_cache(("friend_requests",))
        return JSONResponse({"ok": True, "data": {"handled": True}})

    app.include_router(router)
