"""本地插件卸载：删除 extra_plugin_dirs 源码目录或 uv pip 卸载（跨平台）。"""

from __future__ import annotations

import importlib.metadata
import re
import shutil
from pathlib import Path  # noqa: TC003
from typing import TYPE_CHECKING, Any

from nonebot import logger

from pallas.console.webui.community_plugin_install import uninstall_community_plugin
from pallas.console.webui.extension_install import (
    ExtensionInstallError,
    pip_package_installed,
    run_uv_command,
    tail_output,
    webui_extension_install_enabled,
)
from pallas.core.foundation.config.repo_settings import resolve_extra_plugin_dirs
from pallas.core.foundation.paths import PROJECT_ROOT
from pallas.core.platform.bot_runtime.plugin_matrix import extra_package_for_plugin

if TYPE_CHECKING:
    from collections.abc import Callable

    ProgressReporter = Callable[[int, str], None]

UNINSTALL_TIMEOUT_S = 120.0


def _report(on_progress: ProgressReporter | None, percent: int, message: str) -> None:
    if on_progress is not None:
        on_progress(percent, message)


class LocalPluginUninstallError(Exception):
    def __init__(self, detail: str, *, status_code: int = 400) -> None:
        self.detail = detail
        self.status_code = status_code
        super().__init__(detail)


def resolve_plugin_source_dir(source_dir: str | None) -> Path | None:
    """校验并解析源码目录：必须直接位于某个 extra_plugin_dirs 根下的一级插件目录。"""
    rel = (source_dir or "").strip().replace("\\", "/")
    if not rel or rel.startswith("/") or re.match(r"^[A-Za-z]:", rel):
        return None
    try:
        root = PROJECT_ROOT.resolve()
        path = (PROJECT_ROOT / rel).resolve()
    except OSError:
        return None
    if not path.is_relative_to(root):
        return None
    for raw in resolve_extra_plugin_dirs():
        base = (PROJECT_ROOT / raw).resolve()
        try:
            if path.parent == base:
                return path
        except OSError:
            continue
    return None


def resolve_pip_distribution(
    plugin_id: str,
    module_name: str,
    *,
    top_level_distributions: dict[str, list[str]] | None = None,
) -> str | None:
    """解析插件对应的已安装 pip distribution 名。"""
    top = (module_name or "").strip().split(".", 1)[0]
    candidates: list[str] = []
    if top:
        try:
            distributions = top_level_distributions or importlib.metadata.packages_distributions()
            candidates.extend(distributions.get(top, ()))
        except Exception:  # noqa: BLE001
            pass
    if not candidates:
        pkg = extra_package_for_plugin(plugin_id)
        if pkg:
            candidates.append(pkg)
    for dist in candidates:
        name = (dist or "").strip()
        if not name:
            continue
        try:
            importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            continue
        return name
    return None


def plugin_uninstall_info(
    *,
    plugin_id: str,
    plugin_source: str,
    plugin_source_dir: str | None,
    module_name: str,
    top_level_distributions: dict[str, list[str]] | None = None,
) -> dict[str, Any]:
    """按目录行来源推导可卸载信息（供管理页展示与后端分发）。"""
    source = (plugin_source or "").strip()
    kind: str | None = None
    target: str | None = None
    if source == "local":
        path = resolve_plugin_source_dir(plugin_source_dir)
        if path is not None and path.is_dir():
            kind = "dir"
            target = (plugin_source_dir or "").strip() or None
    elif source in ("pip", "nonebot"):
        dist = resolve_pip_distribution(
            plugin_id,
            module_name,
            top_level_distributions=top_level_distributions,
        )
        if dist and webui_extension_install_enabled():
            kind = "pip"
            target = dist
    elif source == "community":
        kind = "community"
        target = plugin_id
    elif source in ("official", "extra"):
        pkg = extra_package_for_plugin(plugin_id)
        if pkg and pip_package_installed(pkg) and webui_extension_install_enabled():
            kind = "official"
            target = pkg
    return {
        "uninstallable": kind is not None,
        "uninstall_kind": kind,
        "uninstall_target": target,
    }


def _catalog_row_for_plugin(plugin_id: str) -> dict[str, Any] | None:
    from pallas.console.webui.plugin_catalog import build_plugin_catalog_rows

    pid = (plugin_id or "").strip()
    if not pid:
        return None
    for row in build_plugin_catalog_rows():
        if row.get("name") == pid or row.get("resolved_plugin_id") == pid:
            return row
    return None


async def uninstall_local_plugin(
    plugin_id: str,
    *,
    on_progress: ProgressReporter | None = None,
) -> dict[str, str | bool]:
    """统一卸载入口：按插件来源分发（dir / pip / community / official）。"""
    pid = (plugin_id or "").strip()
    if not pid:
        raise LocalPluginUninstallError("缺少插件名")
    row = _catalog_row_for_plugin(pid)
    if row is None:
        raise LocalPluginUninstallError(f"未找到插件「{pid}」")
    source = str(row.get("plugin_source") or "")
    source_dir = row.get("plugin_source_dir")
    module_name = str(row.get("module") or "")

    _report(on_progress, 5, "准备卸载…")

    if source == "local":
        path = resolve_plugin_source_dir(source_dir)
        if path is None or not path.is_dir():
            _report(on_progress, 100, "无需卸载")
            return {
                "plugin_id": pid,
                "uninstall_kind": "dir",
                "installed": False,
                "needs_restart": True,
                "already_removed": True,
                "message": f"{source_dir or pid} 不存在，无需卸载。",
            }
        logger.info("[WebUI] 卸载本地插件（源码目录），plugin [{}]、path [{}]", pid, path)
        _report(on_progress, 40, f"删除 {path}…")
        try:
            shutil.rmtree(path)
        except OSError as e:
            raise LocalPluginUninstallError(f"删除目录失败：{e}", status_code=502) from e
        _report(on_progress, 95, "删除完成")
        return {
            "plugin_id": pid,
            "uninstall_kind": "dir",
            "installed": False,
            "needs_restart": True,
            "already_removed": False,
            "message": f"已删除 {path}，请重启 Bot 后生效。",
        }

    if source in ("pip", "nonebot"):
        dist = resolve_pip_distribution(pid, module_name)
        if not dist:
            _report(on_progress, 100, "无需卸载")
            return {
                "plugin_id": pid,
                "uninstall_kind": "pip",
                "installed": False,
                "needs_restart": True,
                "already_removed": True,
                "message": "未检测到对应 pip 包，无需卸载。",
            }
        logger.info("[WebUI] 卸载本地插件（pip），plugin [{}]、distribution [{}]", pid, dist)
        _report(on_progress, 25, "执行 uv pip uninstall…")
        try:
            code, out, err = await run_uv_command(UNINSTALL_TIMEOUT_S, "pip", "uninstall", dist)
        except ExtensionInstallError as e:
            raise LocalPluginUninstallError(e.detail, status_code=e.status_code) from e
        if code != 0:
            detail = err or out or "(无输出)"
            raise LocalPluginUninstallError(
                f"uv pip uninstall 失败：{tail_output(detail)}",
                status_code=502,
            )
        _report(on_progress, 95, "卸载完成")
        return {
            "plugin_id": pid,
            "uninstall_kind": "pip",
            "installed": False,
            "needs_restart": True,
            "already_removed": False,
            "message": f"已卸载 pip 包 {dist}，请重启 Bot 后生效。",
        }

    if source == "community":
        target_pid = pid
        if source_dir:
            base = Path(source_dir.replace("\\", "/")).name
            if base:
                target_pid = base
        return await uninstall_community_plugin(target_pid, on_progress=on_progress)

    if source == "official":
        from pallas.console.webui.extension_install import uninstall_official_extension

        pkg = extra_package_for_plugin(pid)
        if not pkg:
            raise LocalPluginUninstallError(f"插件「{pid}」缺少官方包名")
        return await uninstall_official_extension(pkg, on_progress=on_progress)

    raise LocalPluginUninstallError(f"插件「{pid}」不可卸载（来源 {source}）")
