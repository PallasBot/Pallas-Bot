"""官方扩展清单。"""

from __future__ import annotations

from typing import Any

from pallas.console.cli.bot_process import bot_lifecycle_available
from pallas.console.webui.extension_install import (
    pip_package_installed,
    webui_extension_install_enabled,
)
from pallas.core.foundation.config.repo_settings import read_bootstrap_load_bundled_extra_plugins_mode
from pallas.core.foundation.paths import PROJECT_ROOT
from pallas.core.platform.bot_runtime.plugin_matrix import (
    EXTRA_PACKAGE_PRIORITY,
    EXTRA_PLUGIN_PACKAGES,
    ext_install_cli_for_package,
    extra_package_for_plugin,
    official_extension_activation_policy,
    official_extension_description,
    official_extension_display_name,
    official_extension_repo_url,
    official_extension_visuals,
)
from pallas.core.platform.bot_runtime.plugin_package_aliases import canonical_plugin_package
from pallas.core.plugin_reload import reload_policy_from_metadata

_PLUGINS_ROOT = PROJECT_ROOT / "packages"


def loaded_extra_plugin_ids(plugin_ids: list[str]) -> list[str]:
    try:
        from nonebot import get_loaded_plugins
    except Exception:
        return []
    names: set[str] = set()
    for p in get_loaded_plugins():
        nb = str(getattr(p, "name", "") or "").strip()
        if nb:
            names.add(canonical_plugin_package(nb))
        mod = getattr(p, "module", None)
        mname = getattr(mod, "__name__", "") if mod is not None else ""
        if mname:
            names.add(canonical_plugin_package(mname.rsplit(".", 1)[-1]))
    return [pid for pid in plugin_ids if pid in names]


def loaded_extra_reload_policies(plugin_ids: list[str]) -> dict[str, str]:
    try:
        from nonebot import get_loaded_plugins
    except Exception:
        return {}
    target_ids = {canonical_plugin_package(pid) for pid in plugin_ids}
    policies: dict[str, str] = {}
    for plugin in get_loaded_plugins():
        candidates = {
            canonical_plugin_package(str(getattr(plugin, "name", "") or "").strip()),
        }
        mod = getattr(plugin, "module", None)
        mname = getattr(mod, "__name__", "") if mod is not None else ""
        if mname:
            candidates.add(canonical_plugin_package(mname.rsplit(".", 1)[-1]))
        meta = getattr(plugin, "metadata", None)
        policy = reload_policy_from_metadata(meta)
        for candidate in candidates:
            if candidate and candidate in target_ids:
                policies[candidate] = policy
    return policies


def build_official_extension_rows() -> list[dict[str, Any]]:
    """按 pip 包聚合 extra 插件。"""
    from pallas.console.webui.plugin_update_snapshot import load_snapshot

    update_snapshot = load_snapshot()
    official_updates = update_snapshot.get("official") or {}
    by_package: dict[str, list[str]] = {}
    for plugin_id, package in sorted(EXTRA_PLUGIN_PACKAGES.items()):
        by_package.setdefault(package, []).append(plugin_id)

    rows: list[dict[str, Any]] = []
    for package in sorted(by_package.keys(), key=lambda p: (EXTRA_PACKAGE_PRIORITY.get(p, "P9"), p)):
        plugin_ids = sorted(by_package[package])
        bundled = [pid for pid in plugin_ids if (_PLUGINS_ROOT / pid).is_dir()]
        loaded = loaded_extra_plugin_ids(plugin_ids)
        reload_policies = loaded_extra_reload_policies(plugin_ids)
        pip_installed = pip_package_installed(package)
        repo_url = official_extension_repo_url(package)
        visuals = official_extension_visuals(package)
        bundled_load_mode = read_bootstrap_load_bundled_extra_plugins_mode()
        if loaded:
            status = "installed"
        elif pip_installed:
            status = "pip_installed"
        elif bundled and bundled_load_mode == "true":
            status = "bundled_active"
        elif bundled and bundled_load_mode == "auto":
            status = "bundled_active"
        elif bundled:
            status = "bundled"
        else:
            status = "external"
        webui_install = webui_extension_install_enabled()
        restart_available = bot_lifecycle_available()
        bundled_load = bundled_load_mode == "true" or (
            bundled_load_mode == "auto" and bool(bundled) and not pip_installed
        )
        snap_entry = official_updates.get(package) if pip_installed else None
        has_update = snap_entry.get("has_update") if isinstance(snap_entry, dict) else None
        installed_ref = snap_entry.get("installed_ref") if isinstance(snap_entry, dict) else None
        latest_ref = snap_entry.get("latest_ref") if isinstance(snap_entry, dict) else None
        rows.append({
            "package": package,
            "plugin_ids": plugin_ids,
            "display_name": official_extension_display_name(package),
            "description": official_extension_description(package),
            "install_cli": ext_install_cli_for_package(package),
            "activation_policy": official_extension_activation_policy(package),
            "reload_policy": next(
                (reload_policies[pid] for pid in plugin_ids if pid in reload_policies),
                None,
            ),
            "repository_url": repo_url,
            "icon": visuals["icon"],
            "cover": visuals["cover"],
            "avatar": visuals["avatar"],
            "bundled_in_repo": bool(bundled),
            "bundled_plugin_ids": bundled,
            "bundled_load_enabled": bundled_load,
            "bundled_load_mode": bundled_load_mode,
            "loaded_plugin_ids": loaded,
            "installed": bool(loaded),
            "pip_installed": pip_installed,
            "install_local_dir": "local/plugins/<插件名>/",
            "webui_install": webui_install,
            "restart_available": restart_available,
            "can_install": webui_install and not pip_installed and not loaded,
            "can_uninstall": webui_install and pip_installed,
            "can_update": webui_install and pip_installed,
            "has_update": has_update,
            "installed_ref": installed_ref,
            "latest_ref": latest_ref,
            "status": status,
        })
    from pallas.console.webui.plugin_store_assets import apply_asset_snapshot_to_rows

    return apply_asset_snapshot_to_rows("official", rows)


def official_extension_for_plugin(plugin_id: str) -> dict[str, Any] | None:
    package = extra_package_for_plugin(plugin_id)
    if not package:
        return None
    for row in build_official_extension_rows():
        if row["package"] == package:
            return row
    return None
