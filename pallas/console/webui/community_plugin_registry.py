"""社区插件商店行：索引 + local/plugins 状态。"""

from __future__ import annotations

import re
from typing import Any

from pallas.console.cli.bot_process import bot_lifecycle_available
from pallas.console.webui.community_plugin_assets import resolve_community_plugin_cover, resolve_community_plugin_icon
from pallas.console.webui.community_plugin_index import load_community_plugin_index_safe
from pallas.console.webui.community_plugin_install import (
    COMMUNITY_PLUGINS_DIR,
    PLUGIN_ID_RE,
    community_plugins_root,
    extra_plugin_dirs_ready,
    local_plugin_installed,
    webui_community_install_enabled,
)
from pallas.console.webui.plugin_registry import loaded_extra_plugin_ids


def github_repo_owner(repository_url: str) -> str | None:
    raw = (repository_url or "").strip()
    if not raw:
        return None
    match = re.match(r"(?:https?://|git@)github\.com[/:]([^/]+)/", raw, flags=re.IGNORECASE)
    if not match:
        return None
    owner = match.group(1).strip()
    return owner or None


def resolve_community_plugin_avatar(entry: dict[str, Any]) -> str | None:
    explicit_author_avatar = str(entry.get("author_avatar") or "").strip()
    if explicit_author_avatar:
        return explicit_author_avatar
    author = str(entry.get("author") or "").strip().lstrip("@")
    if author and "/" not in author:
        return f"https://avatars.githubusercontent.com/{author}?s=64"
    owner = github_repo_owner(str(entry.get("repository_url") or entry.get("repository") or ""))
    if owner:
        return f"https://avatars.githubusercontent.com/{owner}?s=64"
    return None


def community_plugin_status(*, plugin_id: str, local_installed: bool, loaded: bool) -> str:
    if loaded:
        return "loaded"
    if local_installed:
        return "installed"
    return "available"


def list_local_community_plugin_ids() -> list[str]:
    root = community_plugins_root()
    if not root.is_dir():
        return []
    ids: list[str] = []
    for child in sorted(root.iterdir()):
        if not child.is_dir():
            continue
        if not (child / "__init__.py").is_file():
            continue
        name = child.name
        if PLUGIN_ID_RE.fullmatch(name):
            ids.append(name)
    return ids


def local_community_plugin_can_update(plugin_id: str) -> bool:
    if not webui_community_install_enabled():
        return False
    path = community_plugins_root() / plugin_id
    return path.is_dir() and (path / ".git").exists()


def build_community_plugin_row(
    entry: dict[str, Any],
    *,
    update_snapshot: dict[str, Any] | None = None,
) -> dict[str, Any]:
    plugin_id = str(entry["plugin_id"])
    local = local_plugin_installed(plugin_id)
    loaded = plugin_id in loaded_extra_plugin_ids([plugin_id])
    status = community_plugin_status(plugin_id=plugin_id, local_installed=local, loaded=loaded)
    webui_install = webui_community_install_enabled()
    restart_available = bot_lifecycle_available()
    dirs_ready = extra_plugin_dirs_ready()
    icon = resolve_community_plugin_icon(entry)
    has_repo = bool(str(entry.get("repository_url") or "").strip())
    can_update = local and webui_install and (has_repo or local_community_plugin_can_update(plugin_id))
    snap_entry = ((update_snapshot or {}).get("community") or {}).get(plugin_id) if local else None
    has_update = snap_entry.get("has_update") if isinstance(snap_entry, dict) else None
    installed_ref = snap_entry.get("installed_ref") if isinstance(snap_entry, dict) else None
    latest_ref = snap_entry.get("latest_ref") if isinstance(snap_entry, dict) else None
    return {
        "plugin_id": plugin_id,
        "name": entry.get("name") or plugin_id,
        "description": entry.get("description") or "",
        "repository_url": entry.get("repository_url"),
        "ref": entry.get("ref") or "main",
        "author": entry.get("author") or "",
        "homepage": entry.get("homepage"),
        "icon": icon,
        "cover": resolve_community_plugin_cover(entry),
        "avatar": resolve_community_plugin_avatar(entry),
        "tags": list(entry.get("tags") or []),
        "min_pallas_version": entry.get("min_pallas_version"),
        "local_only": bool(entry.get("local_only")),
        "local_installed": local,
        "loaded": loaded,
        "local_path": f"{COMMUNITY_PLUGINS_DIR}/{plugin_id}/" if local else None,
        "install_local_dir": f"{COMMUNITY_PLUGINS_DIR}/<插件 ID>/",
        "extra_plugin_dirs_ready": dirs_ready,
        "webui_install": webui_install,
        "restart_available": restart_available,
        "can_install": webui_install and not local and has_repo,
        "can_uninstall": local,
        "can_update": can_update,
        "has_update": has_update,
        "installed_ref": installed_ref,
        "latest_ref": latest_ref,
        "status": status,
        "activation_policy": "hot-reloadable",
    }


async def build_community_plugin_store() -> dict[str, Any]:
    from pallas.console.webui.plugin_store_assets import apply_asset_snapshot_to_rows
    from pallas.console.webui.plugin_update_snapshot import load_snapshot, snapshot_checked_at

    index = await load_community_plugin_index_safe()
    update_snapshot = load_snapshot()
    rows = [build_community_plugin_row(entry, update_snapshot=update_snapshot) for entry in index.get("plugins") or []]
    rows = apply_asset_snapshot_to_rows("community", rows)
    return {
        "source": index.get("source"),
        "meta": index.get("meta") or {},
        "error": index.get("error"),
        "extra_plugin_dirs_ready": extra_plugin_dirs_ready(),
        "webui_install": webui_community_install_enabled(),
        "restart_available": bot_lifecycle_available(),
        "activation_policy": "hot-reloadable",
        "update_checked_at": snapshot_checked_at(),
        "plugins": rows,
    }
