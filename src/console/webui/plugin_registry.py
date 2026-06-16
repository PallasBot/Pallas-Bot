"""官方扩展清单：S5/S6 WebUI 商店与安装指引的数据源。"""

from __future__ import annotations

from typing import Any

from src.foundation.paths import PROJECT_ROOT
from src.platform.bot_runtime.plugin_matrix import (
    EXTRA_PACKAGE_PRIORITY,
    EXTRA_PLUGIN_PACKAGES,
    extra_package_for_plugin,
    official_extension_repo_url,
    uv_extra_for_package,
)

_PLUGINS_ROOT = PROJECT_ROOT / "src" / "plugins"


def build_official_extension_rows() -> list[dict[str, Any]]:
    """按 pip 包聚合 extra 插件，供 WebUI 展示与后续一键安装。"""
    by_package: dict[str, list[str]] = {}
    for plugin_id, package in sorted(EXTRA_PLUGIN_PACKAGES.items()):
        by_package.setdefault(package, []).append(plugin_id)

    rows: list[dict[str, Any]] = []
    for package in sorted(by_package.keys(), key=lambda p: (EXTRA_PACKAGE_PRIORITY.get(p, "P9"), p)):
        plugin_ids = sorted(by_package[package])
        uv_extra = uv_extra_for_package(package)
        bundled = [pid for pid in plugin_ids if (_PLUGINS_ROOT / pid).is_dir()]
        repo_url = official_extension_repo_url(package)
        rows.append({
            "package": package,
            "plugin_ids": plugin_ids,
            "priority": EXTRA_PACKAGE_PRIORITY.get(package, "P2"),
            "uv_extra": uv_extra,
            "install_cli": f"uv sync --extra {uv_extra}" if uv_extra else None,
            "repository_url": repo_url,
            "bundled_in_repo": bool(bundled),
            "bundled_plugin_ids": bundled,
            "install_local_dir": "local/plugins/<插件名>/",
            "webui_install": False,
            "status": "external" if repo_url and not bundled else ("bundled" if bundled else "external"),
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
