"""Pallas-Bot WebUI console API: system, home, bots, shard observability."""

from __future__ import annotations

import asyncio
import os
import platform
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any

from fastapi import APIRouter, Header, HTTPException, Query
from fastapi.responses import JSONResponse
from nonebot import get_bots, get_driver, logger
from nonebot.adapters import Bot as BaseBot  # noqa: TC002
from pydantic import BaseModel, ConfigDict

from packages.pb_webui.console_openapi_models import (
    IngressDispatchData as _IngressDispatchData,
)
from packages.pb_webui.console_openapi_models import (
    IngressDispatchHistoryData as _IngressDispatchHistoryData,
)
from packages.pb_webui.console_openapi_models import (
    ShardObservabilityData as _ShardObservabilityData,
)
from packages.pb_webui.console_openapi_models import (
    SystemRestartAvailabilityData as _SystemRestartAvailabilityData,
)
from packages.pb_webui.console_openapi_models import (
    _ApiOkResponse,
)
from pallas.core.shared.utils.format_exception import format_exception_for_log

from .console_meta_store import get_console_meta, merge_console_version_from_disk
from .console_read_cache import cached_read
from .extended_common import (
    check_pallas_write_token,
    shard_hub_console,
)
from .plugins_console_api import _list_plugins_dict

if TYPE_CHECKING:
    from .config import Config


class _SystemRestartBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    workers_only: bool = False


_BOT_SESSION_CONNECTED_UNIX: dict[str, int] = {}
_BOT_SESSION_HOOKS_REGISTERED = False


def _ensure_bot_session_hooks() -> None:
    """进程内记录 Bot 接入时刻"""
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


def _resolve_local_onebot_ws_port() -> int | None:
    """本进程 OneBot 反向 WS 监听端口（分片 worker / unified 的 PORT）。"""
    try:
        from pallas.core.platform.shard.worker_port import current_worker_port

        wp = current_worker_port()
        if wp is not None and 1 <= int(wp) <= 65535:
            return int(wp)
    except Exception:  # noqa: BLE001
        pass
    try:
        port = getattr(get_driver().config, "port", None)
        if port is not None:
            p = int(port)
            if 1 <= p <= 65535:
                return p
    except Exception:  # noqa: BLE001
        pass
    raw = (os.environ.get("PORT") or "").strip()
    if raw.isdigit():
        p = int(raw)
        if 1 <= p <= 65535:
            return p
    return None


def _local_shard_id_for_bots() -> int | None:
    try:
        from pallas.core.platform.shard import context as shard_ctx
        from pallas.core.platform.shard.registry.config import get_shard_registry_settings

        if not shard_ctx.sharding_active():
            return None
        s = get_shard_registry_settings()
        if s.role != "worker":
            return None
        return int(s.shard_id)
    except Exception:  # noqa: BLE001
        return None


def _list_bots_dict() -> list[dict[str, Any]]:

    if shard_hub_console():
        from pallas.core.platform.shard.presence import list_connected_bots_for_webui

        return list_connected_bots_for_webui()

    ws_port = _resolve_local_onebot_ws_port()
    shard_id = _local_shard_id_for_bots()
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
        row: dict[str, Any] = {
            "connection_key": str(key),
            "self_id": self_id,
            "adapter": adapter,
            "connected_at_unix": _BOT_SESSION_CONNECTED_UNIX.get(str(key)),
            "ws_port": ws_port,
        }
        if shard_id is not None:
            row["shard_id"] = shard_id
        rows.append(row)
    return rows


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


def _home_overview_slice(result: Any, label: str) -> Any:
    if isinstance(result, BaseException):
        logger.warning("[WebUI] home/overview {} 失败: {}", label, format_exception_for_log(result))
        return None
    return result


async def _home_overview_payload() -> dict[str, Any]:
    from packages.pb_webui import extended_api as ext

    from .api import read_current_health_payload

    async def load_system() -> dict[str, Any]:
        return await cached_read(
            key="system",
            loader=lambda: asyncio.to_thread(ext._system_dict),
            ttl_sec=0.8,
            stale_sec=8.0,
        )

    async def load_bots() -> list[dict[str, Any]]:
        return await cached_read(
            key="bots",
            loader=lambda: asyncio.to_thread(ext._list_bots_dict),
            ttl_sec=0.9,
            stale_sec=15.0,
        )

    async def load_instances() -> dict[str, Any]:
        return await cached_read(
            key="instances",
            loader=ext._instances_payload,
            ttl_sec=1.0,
            stale_sec=20.0,
        )

    async def load_plugins() -> list[dict[str, Any]]:
        return await cached_read(
            key="plugins",
            loader=lambda: asyncio.to_thread(ext._list_plugins_dict),
            ttl_sec=1.6,
            stale_sec=25.0,
        )

    async def load_message_stats() -> dict[str, Any]:
        return await cached_read(
            key="message-stats:all",
            loader=lambda: ext._message_stats_overview(self_id=None),
            ttl_sec=2.0,
            stale_sec=10.0,
        )

    async def load_plugin_run_stats() -> dict[str, Any]:
        return await cached_read(
            key="plugin-run-stats:all:logsrc:all:tbl:0:view:full",
            loader=lambda: asyncio.to_thread(
                ext._plugin_run_stats_overview,
                self_id=None,
                log_source="all",
                tb_limit=0,
                include_log_errors=False,
            ),
            ttl_sec=2.0,
            stale_sec=10.0,
        )

    async def load_community_stats() -> dict[str, Any]:
        from pallas.product.community_stats.public_stats import fetch_community_public_stats

        return await cached_read(
            key="community-stats",
            loader=fetch_community_public_stats,
            ttl_sec=30.0,
            stale_sec=120.0,
        )

    (
        health_res,
        system_res,
        bots_res,
        instances_res,
        plugins_res,
        message_stats_res,
        plugin_run_stats_res,
        community_stats_res,
    ) = await asyncio.gather(
        read_current_health_payload(),
        load_system(),
        load_bots(),
        load_instances(),
        load_plugins(),
        load_message_stats(),
        load_plugin_run_stats(),
        load_community_stats(),
        return_exceptions=True,
    )
    bots_data = _home_overview_slice(bots_res, "bots")
    plugins_data = _home_overview_slice(plugins_res, "plugins")
    return {
        "health": _home_overview_slice(health_res, "health"),
        "system": _home_overview_slice(system_res, "system"),
        "bots": bots_data if isinstance(bots_data, list) else [],
        "instances": _home_overview_slice(instances_res, "instances"),
        "plugins": plugins_data if isinstance(plugins_data, list) else [],
        "message_stats": _home_overview_slice(message_stats_res, "message_stats"),
        "plugin_run_stats": _home_overview_slice(plugin_run_stats_res, "plugin_run_stats"),
        "community_stats": _home_overview_slice(community_stats_res, "community_stats"),
    }


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
    console = get_console_meta()
    sr = str(console.get("static_root", "") or "").strip()
    static_path = Path(sr) if sr else None
    merge_console_version_from_disk(console, static_path)
    return {
        "nonebot2_driver": {
            "host": host_s,
            "port": port_s,
        },
        "superuser_count": n_sup,
        "server_time": time.time(),
        "plugin_count": sum(1 for r in _list_plugins_dict() if r.get("help_visible")),
        "bot_count": len(_list_bots_dict()),
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

        percpu = psutil.cpu_percent(interval=None, percpu=True)
        if isinstance(percpu, (list, tuple)) and len(percpu) > 0:
            cpu_per_core = [round(float(min(100.0, max(0.0, float(x)))), 2) for x in percpu]
            cpu_percent = round(sum(cpu_per_core) / len(cpu_per_core), 2)
        else:
            cpu_percent = float(psutil.cpu_percent(interval=None))
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
        logger.debug("[WebUI] psutil.boot_time 不可用，将尝试其它方式 err={}", e)

    if boot_time is None and sys.platform == "win32":
        try:
            import ctypes

            ms = int(ctypes.windll.kernel32.GetTickCount64())
            boot_time = float(time.time() - ms / 1000.0)
        except Exception as e:  # noqa: BLE001
            logger.debug("[WebUI] Windows GetTickCount64 推算启动时间失败 err={}", e)

    return {
        "platform": platform.platform(),
        "python": platform.python_version(),
        "hostname": hostname_s or None,
        "boot_time": boot_time,
        "cpu_model": cpu_model(),
        "cpu_percent": cpu_percent,
        "cpu_per_core": cpu_per_core,
        "cpu_load_avg": cpu_load_avg,
        "memory": mem,
        "disk": disk,
        "gpu": _gpu_metrics(),
    }


def cpu_model() -> str | None:
    """Return the host CPU model when the operating system exposes one."""
    try:
        system_name = platform.system()
        if system_name == "Linux":
            fallback_model: str | None = None
            for line in Path("/proc/cpuinfo").read_text(encoding="utf-8", errors="replace").splitlines():
                key, sep, value = line.partition(":")
                if not sep:
                    continue
                model = " ".join(value.split())
                if not model:
                    continue
                key = key.strip()
                if key.lower() == "model name":
                    return model
                if key in {"Hardware", "Model"} and fallback_model is None:
                    fallback_model = model
            if fallback_model:
                return fallback_model
        elif system_name == "Darwin":
            model = subprocess.check_output(
                ["sysctl", "-n", "machdep.cpu.brand_string"],
                text=True,
                timeout=1,
            )
            if model := " ".join(model.split()):
                return model
        elif system_name == "Windows":
            import winreg

            key_path = r"HARDWARE\DESCRIPTION\System\CentralProcessor\0"
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, key_path) as key:
                model, _ = winreg.QueryValueEx(key, "ProcessorNameString")
            if model := " ".join(str(model).split()):
                return model
    except Exception:  # noqa: BLE001
        pass

    return " ".join(platform.processor().split()) or None


def register_system_home_router(
    router: APIRouter,
    *,
    x: str,
    plugin_config: Config,
    router_pub: APIRouter | None = None,
) -> None:
    """Register console routes."""

    @router.get(f"{x}/system", include_in_schema=True)
    async def _system() -> JSONResponse:
        async def _load() -> dict[str, Any]:
            return _system_dict()

        data = await cached_read(key="system", loader=_load, ttl_sec=0.8, stale_sec=8.0)
        return JSONResponse({"ok": True, "data": data})

    @router.get(f"{x}/home/overview", include_in_schema=True)
    async def _home_overview() -> JSONResponse:
        async def _load() -> dict[str, Any]:
            return await _home_overview_payload()

        data = await cached_read(key="home-overview", loader=_load, ttl_sec=0.6, stale_sec=6.0)
        return JSONResponse({"ok": True, "data": data})

    @router.post(f"{x}/system/restart", include_in_schema=True)
    async def _system_restart(
        body: _SystemRestartBody,
        token: str | None = Query(default=None),
        x_pallas_token: str | None = Header(default=None, alias="X-Pallas-Token"),
    ) -> JSONResponse:
        check_pallas_write_token(plugin_config, x_pallas_token=x_pallas_token, token=token)
        from pallas.console.cli.bot_process import bot_lifecycle_available, schedule_bot_restart
        from pallas.console.cli.runtime_mode import resolve_bot_mode

        if not bot_lifecycle_available():
            raise HTTPException(
                status_code=503,
                detail="当前环境不支持通过控制台调度 Bot 重启（缺少 scripts/run_*.sh）",
            )

        resolved_mode = resolve_bot_mode("auto")
        workers_only = bool(body.workers_only)
        if workers_only and resolved_mode != "shard":
            raise HTTPException(status_code=400, detail="workers_only 仅适用于分片（shard）部署模式")

        scheduled = schedule_bot_restart(workers_only=workers_only)
        if not scheduled:
            raise HTTPException(status_code=500, detail="重启调度失败")

        mode_label = "workers-restart" if workers_only else "full-restart"
        logger.info(
            "[WebUI] 已调度 Bot 重启 mode={} workers_only={}",
            mode_label,
            workers_only,
        )
        return JSONResponse({
            "ok": True,
            "data": {
                "scheduled": True,
                "mode": mode_label,
                "workers_only": workers_only,
                "bot_runtime_mode": resolved_mode,
                "message": "已安排重启，数秒后进程将重新拉起。",
            },
        })

    @router.get(
        f"{x}/system/restart-availability",
        include_in_schema=True,
        response_model=_ApiOkResponse[_SystemRestartAvailabilityData],
    )
    async def _system_restart_availability() -> dict[str, Any]:
        """壳层判断侧栏重启按钮；轻量、不含 GitHub 等网络请求。"""
        from pallas.console.cli.bot_process import bot_lifecycle_available

        from .manager import inspect_bot_deployment

        deploy = inspect_bot_deployment()
        return {
            "ok": True,
            "data": {
                "restart_available": bot_lifecycle_available(),
                "deployment_mode": deploy.get("deployment_mode", ""),
            },
        }

    @router.get(f"{x}/shard-registry", include_in_schema=True)
    async def _shard_registry() -> JSONResponse:
        from pallas.core.platform.shard.registry import get_shard_registry, rebalance_hint
        from pallas.core.platform.shard.registry.config import get_shard_registry_settings

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

    @router.get(
        f"{x}/shard-observability",
        include_in_schema=True,
        response_model=_ApiOkResponse[_ShardObservabilityData],
    )
    async def _shard_observability() -> dict[str, Any]:
        from pallas.core.platform.shard.observability import aggregate_shard_observability

        async def _load() -> dict[str, Any]:
            return aggregate_shard_observability()

        data = await cached_read(key="shard-observability", loader=_load, ttl_sec=2.0, stale_sec=8.0)
        return {"ok": True, "data": data}

    @router.get(f"{x}/repeater-metrics/history", include_in_schema=True)
    async def _repeater_metrics_history(limit: int = Query(default=168, ge=1, le=24 * 30)) -> JSONResponse:
        from .repeater_metrics_history import read_recent_repeater_metrics_history

        async def _load() -> list[dict[str, Any]]:
            return read_recent_repeater_metrics_history(limit=limit)

        data = await cached_read(
            key=f"repeater-metrics-history:{int(limit)}",
            loader=_load,
            ttl_sec=2.0,
            stale_sec=8.0,
        )
        return JSONResponse({"ok": True, "data": data})

    @router.get(
        f"{x}/ingress-dispatch",
        include_in_schema=True,
        response_model=_ApiOkResponse[_IngressDispatchData],
    )
    async def _ingress_dispatch_metrics() -> dict[str, Any]:
        from pallas.core.platform.shard.dispatch_observability import aggregate_ingress_dispatch

        async def _load() -> dict[str, Any]:
            return aggregate_ingress_dispatch()

        data = await cached_read(key="ingress-dispatch", loader=_load, ttl_sec=2.0, stale_sec=8.0)
        return {"ok": True, "data": data}

    @router.get(
        f"{x}/ingress-dispatch/history",
        include_in_schema=True,
        response_model=_ApiOkResponse[_IngressDispatchHistoryData],
    )
    async def _ingress_dispatch_history(
        window_sec: int = Query(default=3600, ge=15 * 60, le=7 * 24 * 60 * 60),
    ) -> dict[str, Any]:
        from .ingress_metrics_history import read_ingress_metrics_history

        bucket_sec = (
            15
            if window_sec <= 60 * 60
            else 60
            if window_sec <= 6 * 60 * 60
            else 300
            if window_sec <= 24 * 60 * 60
            else 1800
        )

        async def _load() -> dict[str, Any]:
            return read_ingress_metrics_history(window_sec=window_sec, bucket_sec=bucket_sec)

        data = await cached_read(key=f"ingress-dispatch-history:{window_sec}", loader=_load, ttl_sec=2.0, stale_sec=8.0)
        return {"ok": True, "data": data}

    @router.get(f"{x}/bots", include_in_schema=True)
    async def _bots() -> JSONResponse:
        async def _load() -> list[dict[str, Any]]:
            return _list_bots_dict()

        data = await cached_read(key="bots", loader=_load, ttl_sec=0.9, stale_sec=15.0)
        return JSONResponse({"ok": True, "data": data})

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
