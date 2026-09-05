"""插件目录可视资源解析与图层合并。"""

from __future__ import annotations

from pathlib import Path  # noqa: TC003

from pallas.console.webui import plugin_catalog as _repo
from pallas.console.webui.plugin_package_assets import resolve_plugin_package_visual_urls
from pallas.core.platform.bot_runtime.plugin_matrix import is_core_plugin

_BRAND_AVATAR_PATH = "/pallas/assets/brand-avatar.png"


def _resolve_remote_catalog_visuals(plugin_id: str) -> dict[str, str | None]:
    community = _repo.community_plugin_row_for_plugin(plugin_id)
    if community is not None:
        return {
            "avatar": _repo.resolve_community_plugin_avatar(community),
            "icon": _repo.resolve_community_plugin_icon(community),
            "cover": str(community.get("cover") or "").strip() or None,
        }

    from pallas.core.platform.bot_runtime.plugin_matrix import (
        extra_package_for_plugin,
        official_extension_visuals,
    )

    package = extra_package_for_plugin(plugin_id)
    if package:
        visuals = official_extension_visuals(package)
        cover = str(visuals.get("cover") or "").strip() or None
        icon = cover or (str(visuals.get("icon") or "").strip() or None)
        return {
            "avatar": None,
            "icon": icon,
            "cover": cover,
        }

    return {"avatar": None, "icon": None, "cover": None}


def _first_visual_url(*values: str | None) -> str | None:
    for value in values:
        clean = str(value or "").strip()
        if clean:
            return clean
    return None


def _icon_only_from_layer(layer: dict[str, str | None]) -> str | None:
    cover = str(layer.get("cover") or "").strip() or None
    icon = str(layer.get("icon") or "").strip() or None
    if not icon:
        return None
    if cover and icon == cover:
        return None
    return icon


def _merge_catalog_visual_layers(
    local: dict[str, str | None],
    cached: dict[str, str | None],
    remote: dict[str, str | None],
) -> dict[str, str | None]:
    cover = _first_visual_url(local.get("cover"), cached.get("cover"), remote.get("cover"))
    avatar = _first_visual_url(local.get("avatar"), cached.get("avatar"), remote.get("avatar"))
    icon_only = _first_visual_url(
        _icon_only_from_layer(local),
        _icon_only_from_layer(cached),
        _icon_only_from_layer(remote),
    )
    display_icon = cover or icon_only or avatar
    return {"cover": cover, "icon": display_icon, "avatar": avatar}


def resolve_catalog_visuals(
    *,
    plugin_id: str,
    plugin_source: str,
    plugin_root: Path | None = None,
) -> dict[str, str | None]:
    local = resolve_plugin_package_visual_urls(plugin_id=plugin_id, plugin_root=plugin_root)
    from pallas.console.webui.plugin_store_assets import resolve_store_cached_visual_urls_for_plugin

    cached = resolve_store_cached_visual_urls_for_plugin(plugin_id)
    remote = _repo._resolve_remote_catalog_visuals(plugin_id)
    merged = _merge_catalog_visual_layers(local, cached, remote)
    if merged.get("cover") or merged.get("icon") or merged.get("avatar"):
        return merged

    if is_core_plugin(plugin_id) or plugin_source == "core":
        return {"avatar": None, "icon": _BRAND_AVATAR_PATH, "cover": None}

    return {"avatar": None, "icon": None, "cover": None}
