"""社区插件安装/更新/卸载后的生效策略。"""

from __future__ import annotations

from typing import Any, Literal

from nonebot import logger

from pallas.console.cli.bot_process import bot_lifecycle_available, schedule_bot_restart
from pallas.console.cli.extension_activation import activation_pending_note, append_activation_note
from pallas.console.cli.runtime_mode import resolve_bot_mode
from pallas.core.platform.bot_runtime.plugin_loader import hot_load_extra_dir_plugin

CommunityPluginAction = Literal["install", "update", "uninstall"]


def community_activation_policy(action: CommunityPluginAction) -> str:
    if action == "install":
        return "hot-reloadable"
    if action == "update":
        return "workers-restart"
    return "full-restart"


def community_activation_pending_note(
    policy: str | None,
    *,
    action: CommunityPluginAction,
) -> str:
    if action == "update":
        if policy == "workers-restart":
            return "代码已更新；须重启 Worker（分片）或 Bot 后加载新版本（不支持运行时热更）。"
        return "代码已更新；须重启 Bot 后加载新版本（不支持运行时热更）。"
    if action == "uninstall":
        return "已从 local/plugins 删除；须重启 Bot 后卸载内存中的 matcher。"
    return activation_pending_note(policy)


def append_community_activation_result(
    result: dict[str, Any],
    *,
    action: CommunityPluginAction,
    restart: bool,
) -> dict[str, Any]:
    out = dict(result)
    policy = community_activation_policy(action)
    out["activation_policy"] = policy
    out["activation_operation"] = action
    out["activation_action"] = "none"
    out["restart_scheduled"] = False

    if not bot_lifecycle_available():
        out.setdefault("needs_restart", True)
        return out

    mode = resolve_bot_mode("auto")
    dirs_ready = bool(out.get("extra_plugin_dirs_ready"))
    plugin_id = str(out.get("plugin_id") or "").strip()
    installed = bool(out.get("installed")) and not out.get("already_removed")

    if (
        action == "install"
        and policy == "hot-reloadable"
        and mode == "unified"
        and dirs_ready
        and plugin_id
        and installed
    ):
        if hot_load_extra_dir_plugin(plugin_id):
            out["activation_action"] = "hot-reload"
            out["needs_restart"] = False
            logger.info("community plugin {} activated by runtime hot load", plugin_id)
            return out
        if restart:
            logger.warning("community plugin {} hot load failed, fallback to process restart", plugin_id)
            out["hot_load_fallback"] = True
        else:
            out.setdefault("needs_restart", True)
            return out

    if not restart:
        out.setdefault("needs_restart", True)
        return out

    workers_only = mode == "shard"
    scheduled = schedule_bot_restart(mode=mode, workers_only=workers_only)
    out["restart_scheduled"] = scheduled
    if scheduled:
        out["activation_action"] = "workers-restart" if workers_only else "full-restart"
        out["needs_restart"] = False
    return out


def should_append_community_activation_note(result: dict[str, Any], *, restart: bool) -> bool:
    action = str(result.get("activation_action") or "none")
    return bool(restart or result.get("needs_restart") or action != "none")


def append_community_activation_note(
    message: str,
    result: dict[str, Any],
    *,
    action: CommunityPluginAction,
) -> str:
    if (
        action in ("update", "uninstall")
        and result.get("needs_restart")
        and str(result.get("activation_action") or "none") == "none"
    ):
        suffix = community_activation_pending_note(
            str(result.get("activation_policy") or ""),
            action=action,
        )
        return f"{(message or '').strip()} {suffix}".strip()

    base = append_activation_note(message, result)
    if base != (message or "").strip():
        return base
    policy = result.get("activation_policy")
    if result.get("needs_restart") and str(result.get("activation_action") or "none") == "none":
        suffix = community_activation_pending_note(
            str(policy) if policy else None,
            action=action,
        )
        return f"{(message or '').strip()} {suffix}".strip()
    return base
