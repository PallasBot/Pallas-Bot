"""官方扩展安装后的生效策略。"""

from __future__ import annotations

from typing import Any

from nonebot import logger

from pallas.console.cli.bot_process import bot_lifecycle_available, schedule_bot_restart
from pallas.console.cli.runtime_mode import resolve_bot_mode
from pallas.core.platform.bot_runtime.plugin_loader import (
    _load_plugin_module,
    load_apscheduler_plugin_first,
)
from pallas.core.platform.bot_runtime.plugin_matrix import (
    EXTRA_PACKAGE_MODULES,
    official_extension_activation_policy,
)
from pallas.core.plugin_reload.metadata_index import reload_plugin_metadata_index


def _hot_load_package_modules(package: str) -> bool:
    modules = EXTRA_PACKAGE_MODULES.get((package or "").strip(), ())
    if not modules:
        return False
    loaded_short: set[str] = set()
    load_apscheduler_plugin_first(role_label="runtime", loaded_short=loaded_short)
    loaded = False
    for module_path in modules:
        loaded = _load_plugin_module(module_path, role_label="runtime", loaded_short=loaded_short) or loaded
    if loaded:
        reload_plugin_metadata_index()
    return loaded


def activation_pending_note(policy: str | None) -> str:
    if policy == "hot-reloadable":
        return "理论支持热加载；当前环境仍需重启生效，可选择「安装并重启」尝试立即加载。"
    if policy == "workers-restart":
        return "需重启 Worker（分片部署）或 Bot 进程后生效。"
    if policy == "full-restart":
        return "需全进程重启后生效。"
    return "请重启 Bot 后生效。"


def append_activation_result(
    result: dict[str, Any],
    *,
    restart: bool,
) -> dict[str, Any]:
    out = dict(result)
    package = str(out.get("package") or "").strip()
    policy = official_extension_activation_policy(package)
    out["activation_policy"] = policy
    out["activation_action"] = "none"
    out["restart_scheduled"] = False

    if not bot_lifecycle_available() or not package or policy is None:
        return out

    mode = resolve_bot_mode("auto")

    if policy == "hot-reloadable" and mode == "unified":
        if _hot_load_package_modules(package):
            out["activation_action"] = "hot-reload"
            out["needs_restart"] = False
            logger.info("official extension {} activated by runtime hot load", package)
            return out
        if restart:
            logger.warning("official extension {} hot load failed, fallback to process restart", package)
            out["hot_load_fallback"] = True
        else:
            return out

    if not restart:
        return out

    workers_only = policy == "workers-restart" and mode == "shard"
    scheduled = schedule_bot_restart(mode=mode, workers_only=workers_only)
    out["restart_scheduled"] = scheduled
    if scheduled:
        out["activation_action"] = "workers-restart" if workers_only else "full-restart"
    return out


def append_activation_note(message: str, result: dict[str, Any]) -> str:
    base = (message or "").strip()
    action = str(result.get("activation_action") or "none")
    scheduled = bool(result.get("restart_scheduled"))
    policy = result.get("activation_policy")
    if action == "hot-reload":
        suffix = "已在当前进程直接加载。"
    elif scheduled and action == "full-restart" and result.get("hot_load_fallback"):
        suffix = "运行时热加载失败，已改为安排全进程重启。"
    elif scheduled and action == "workers-restart":
        suffix = "已安排仅重启 worker。"
    elif scheduled and action == "full-restart":
        suffix = "已安排 Bot 重启。"
    elif scheduled:
        suffix = "已安排生效操作。"
    elif result.get("needs_restart") and action == "none":
        suffix = activation_pending_note(str(policy) if policy else None)
    else:
        suffix = ""
    return f"{base} {suffix}".strip() if suffix else base
