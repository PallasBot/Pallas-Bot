"""社区插件安装与可选重启。"""

from __future__ import annotations

from pallas.console.cli.community_plugin_activation import (
    append_community_activation_note,
    append_community_activation_result,
    should_append_community_activation_note,
)
from pallas.console.webui.community_plugin_install import (
    CommunityPluginInstallError,
    install_community_plugin,
    uninstall_community_plugin,
    update_community_plugin,
)


async def install_community_plugin_with_options(
    plugin_id: str,
    *,
    repository_url: str,
    ref: str = "main",
    restart: bool = False,
) -> dict[str, str | bool]:
    result = await install_community_plugin(
        plugin_id,
        repository_url=repository_url,
        ref=ref,
    )
    result = append_community_activation_result(dict(result), action="install", restart=restart)
    if should_append_community_activation_note(result, restart=restart):
        result["message"] = append_community_activation_note(
            str(result.get("message") or ""),
            result,
            action="install",
        )
    return result


async def update_community_plugin_with_options(
    plugin_id: str,
    *,
    ref: str = "main",
    restart: bool = False,
) -> dict[str, str | bool]:
    result = await update_community_plugin(plugin_id, ref=ref)
    result = append_community_activation_result(dict(result), action="update", restart=restart)
    if should_append_community_activation_note(result, restart=restart):
        result["message"] = append_community_activation_note(
            str(result.get("message") or ""),
            result,
            action="update",
        )
    return result


async def uninstall_community_plugin_with_options(
    plugin_id: str,
    *,
    restart: bool = False,
) -> dict[str, str | bool]:
    result = await uninstall_community_plugin(plugin_id)
    result = append_community_activation_result(dict(result), action="uninstall", restart=restart)
    if should_append_community_activation_note(result, restart=restart):
        result["message"] = append_community_activation_note(
            str(result.get("message") or ""),
            result,
            action="uninstall",
        )
    return result


__all__ = [
    "CommunityPluginInstallError",
    "install_community_plugin_with_options",
    "uninstall_community_plugin_with_options",
    "update_community_plugin_with_options",
]
