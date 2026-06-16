"""官方扩展清单。"""

from __future__ import annotations

from typing import Any

from src.console.cli.bot_process import bot_lifecycle_available
from src.console.webui.extension_install import (
    pip_package_installed,
    webui_extension_install_enabled,
)
from src.foundation.paths import PROJECT_ROOT
from src.platform.bot_runtime.plugin_matrix import (
    EXTRA_PACKAGE_PRIORITY,
    EXTRA_PLUGIN_PACKAGES,
    extra_package_for_plugin,
    official_extension_repo_url,
    uv_extra_for_package,
)

_PLUGINS_ROOT = PROJECT_ROOT / "src" / "plugins"


def loaded_extra_plugin_ids(plugin_ids: list[str]) -> list[str]:
    try:
        from nonebot import get_loaded_plugins
    except Exception:
        return []
    names: set[str] = set()
    for p in get_loaded_plugins():
        nb = str(getattr(p, "name", "") or "").strip()
        if nb:
            names.add(nb)
        mod = getattr(p, "module", None)
        mname = getattr(mod, "__name__", "") if mod is not None else ""
        if mname:
            names.add(mname.rsplit(".", 1)[-1])
    return [pid for pid in plugin_ids if pid in names]


def build_official_extension_rows() -> list[dict[str, Any]]:
    """按 pip 包聚合 extra 插件。"""
    by_package: dict[str, list[str]] = {}
    for plugin_id, package in sorted(EXTRA_PLUGIN_PACKAGES.items()):
        by_package.setdefault(package, []).append(plugin_id)

    rows: list[dict[str, Any]] = []
    for package in sorted(by_package.keys(), key=lambda p: (EXTRA_PACKAGE_PRIORITY.get(p, "P9"), p)):
        plugin_ids = sorted(by_package[package])
        uv_extra = uv_extra_for_package(package)
        bundled = [pid for pid in plugin_ids if (_PLUGINS_ROOT / pid).is_dir()]
        loaded = loaded_extra_plugin_ids(plugin_ids)
        pip_installed = pip_package_installed(package)
        repo_url = official_extension_repo_url(package)
        if loaded:
            status = "installed"
        elif pip_installed:
            status = "pip_installed"
        elif bundled:
            status = "bundled"
        else:
            status = "external"
        webui_install = webui_extension_install_enabled()
        restart_available = bot_lifecycle_available()
        rows.append({
            "package": package,
            "plugin_ids": plugin_ids,
            "priority": EXTRA_PACKAGE_PRIORITY.get(package, "P2"),
            "uv_extra": uv_extra,
            "install_cli": f"uv sync --extra {uv_extra}" if uv_extra else None,
            "repository_url": repo_url,
            "bundled_in_repo": bool(bundled),
            "bundled_plugin_ids": bundled,
            "loaded_plugin_ids": loaded,
            "installed": bool(loaded),
            "pip_installed": pip_installed,
            "install_local_dir": "local/plugins/<插件名>/",
            "webui_install": webui_install,
            "restart_available": restart_available,
            "can_install": webui_install and not pip_installed and not loaded,
            "can_uninstall": webui_install and pip_installed,
            "status": status,
        })
    return rows


def official_extension_for_plugin(plugin_id: str) -> dict[str, Any] | None:
    package = extra_package_for_plugin(plugin_id)
    if not package:
        return None
    for row in build_official_extension_rows():
        if row["package"] == package:
            return row
    return None
