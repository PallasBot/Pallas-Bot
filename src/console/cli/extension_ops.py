"""官方扩展安装与可选重启。"""

from __future__ import annotations

from src.console.cli.bot_process import bot_lifecycle_available, schedule_bot_restart
from src.console.webui.extension_install import (
    ExtensionInstallError,
    install_official_extension,
    uninstall_official_extension,
)


def append_restart_note(message: str, *, scheduled: bool) -> str:
    base = (message or "").strip()
    if scheduled:
        suffix = "已安排 Bot 重启。"
        return f"{base} {suffix}".strip() if base else suffix
    if base:
        return base
    return "请重启 Bot 后生效。"


async def install_official_extension_with_options(
    package: str,
    *,
    restart: bool = False,
) -> dict[str, str | bool]:
    result = await install_official_extension(package)
    scheduled = False
    if restart and bot_lifecycle_available():
        scheduled = schedule_bot_restart()
    result = dict(result)
    result["restart_scheduled"] = scheduled
    if restart or result.get("needs_restart"):
        result["message"] = append_restart_note(str(result.get("message") or ""), scheduled=scheduled)
    return result


async def uninstall_official_extension_with_options(
    package: str,
    *,
    restart: bool = False,
) -> dict[str, str | bool]:
    result = await uninstall_official_extension(package)
    scheduled = False
    if restart and bot_lifecycle_available():
        scheduled = schedule_bot_restart()
    result = dict(result)
    result["restart_scheduled"] = scheduled
    if restart or result.get("needs_restart"):
        result["message"] = append_restart_note(str(result.get("message") or ""), scheduled=scheduled)
    return result


__all__ = [
    "ExtensionInstallError",
    "install_official_extension_with_options",
    "uninstall_official_extension_with_options",
]
