"""帮助图插件图标：复用控制台 catalog 视觉与商店快照。"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont

from pallas.console.webui.plugin_catalog import (
    discover_extra_plugin_packages,
    infer_plugin_source,
    resolved_plugin_identity,
)
from pallas.console.webui.plugin_package_assets import (
    PACKAGE_ASSET_CANDIDATE_PATHS,
    resolve_plugin_package_asset_file,
)
from pallas.console.webui.plugin_package_assets import (
    PUBLIC_PREFIX as PLUGIN_ASSETS_PUBLIC_PREFIX,
)
from pallas.console.webui.plugin_store_assets import load_snapshot
from pallas.core.foundation.paths import plugin_data_dir, project_path

from .help_theme import resolve_help_font_path

_STORE_PREFIX = "/pallas/store-assets/"
_BRAND_AVATAR_URL = "/pallas/assets/brand-avatar.png"
_LOCAL_ASSET_NAMES = PACKAGE_ASSET_CANDIDATE_PATHS


def plugin_cover_hue(seed: str) -> int:
    """与 WebUI pluginCoverHue 一致，用于无图 fallback。"""
    digest = hashlib.md5((seed or "plugin").encode("utf-8")).hexdigest()
    return int(digest[:8], 16) % 360


def resolve_help_visual_urls(plugin: Any) -> dict[str, str | None]:
    from pallas.console.webui.plugin_catalog import resolve_catalog_visuals

    mod = getattr(plugin, "module", None)
    module_name = getattr(mod, "__name__", "") if mod is not None else ""
    nb_name = str(getattr(plugin, "name", "") or "")
    plugin_id = resolved_plugin_identity(nb_name, module_name)
    package = plugin_id or nb_name
    extra_pkgs = discover_extra_plugin_packages()
    plugin_source, _ = infer_plugin_source(package, plugin, extra_pkgs=extra_pkgs)
    mod = getattr(plugin, "module", None)
    file_path = getattr(mod, "__file__", "") if mod is not None else ""
    plugin_root = Path(file_path).resolve().parent if file_path else None
    visuals = resolve_catalog_visuals(
        plugin_id=plugin_id or package,
        plugin_source=plugin_source,
        plugin_root=plugin_root,
    )
    return {
        "cover": str(visuals.get("cover") or "").strip() or None,
        "icon": str(visuals.get("icon") or "").strip() or None,
        "avatar": str(visuals.get("avatar") or "").strip() or None,
    }


def pick_help_icon_url(visuals: dict[str, str | None]) -> str | None:
    return visuals.get("cover") or visuals.get("icon") or visuals.get("avatar")


def local_path_from_visual_url(url: str | None) -> Path | None:
    raw = (url or "").strip()
    if not raw:
        return None
    if raw.startswith(_STORE_PREFIX):
        rel = raw[len(_STORE_PREFIX) :].lstrip("/")
        path = plugin_data_dir("pb_webui", create=False) / "store-assets" / rel
        return path if path.is_file() else None
    if raw.startswith(f"{PLUGIN_ASSETS_PUBLIC_PREFIX}/"):
        rel = raw[len(PLUGIN_ASSETS_PUBLIC_PREFIX) + 1 :]
        if "/" in rel:
            plugin_id, asset_rel = rel.split("/", 1)
            path = resolve_plugin_package_asset_file(plugin_id, asset_rel)
            return path
    if raw == _BRAND_AVATAR_URL or raw.endswith("/assets/brand-avatar.png"):
        path = project_path("packages/pb_webui/static/brand-avatar.png")
        return path if path.is_file() else None
    if raw.startswith(("http://", "https://")):
        return _snapshot_path_for_source_url(raw)
    path = Path(raw)
    if path.is_file():
        return path
    project = project_path(raw)
    return project if project.is_file() else None


def _snapshot_path_for_source_url(source_url: str) -> Path | None:
    snapshot = load_snapshot()
    for bucket in snapshot.values():
        if not isinstance(bucket, dict):
            continue
        for entry in bucket.values():
            if not isinstance(entry, dict):
                continue
            assets = entry.get("assets")
            if not isinstance(assets, dict):
                continue
            for asset in assets.values():
                if not isinstance(asset, dict):
                    continue
                if str(asset.get("source_url") or "").strip() != source_url:
                    continue
                rel = str(asset.get("relative_path") or "").strip()
                if not rel:
                    continue
                path = plugin_data_dir("pb_webui", create=False) / "store-assets" / rel
                if path.is_file():
                    return path
    return None


def local_plugin_asset_path(plugin: Any) -> Path | None:
    mod = getattr(plugin, "module", None)
    file_path = getattr(mod, "__file__", "") if mod is not None else ""
    if not file_path:
        return None
    root = Path(file_path).resolve().parent
    for rel in _LOCAL_ASSET_NAMES:
        candidate = root / rel
        if candidate.is_file():
            return candidate
    return None


def resolve_help_icon_path(plugin: Any) -> Path | None:
    local_path = local_plugin_asset_path(plugin)
    if local_path is not None:
        return local_path
    visuals = resolve_help_visual_urls(plugin)
    icon_url = pick_help_icon_url(visuals)
    if icon_url:
        path = local_path_from_visual_url(icon_url)
        if path is not None:
            return path
    return local_path_from_visual_url(_BRAND_AVATAR_URL)


def brand_avatar_icon_path() -> Path | None:
    return local_path_from_visual_url(_BRAND_AVATAR_URL)


def load_brand_avatar_icon(size: int) -> Image.Image | None:
    path = brand_avatar_icon_path()
    if path is None:
        return None
    try:
        with Image.open(path) as opened:
            return rounded_image(opened, size, max(8, size // 5))
    except OSError:
        return None


def help_font(size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(str(resolve_help_font_path()), size)


def rounded_image(image: Image.Image, size: int, radius: int) -> Image.Image:
    work = image.convert("RGBA")
    if work.size != (size, size):
        work = work.resize((size, size), Image.Resampling.LANCZOS)
    mask = Image.new("L", (size, size), 0)
    draw = ImageDraw.Draw(mask)
    draw.rounded_rectangle((0, 0, size, size), radius=radius, fill=255)
    out = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    out.paste(work, (0, 0), mask)
    return out


def fallback_icon_image(seed: str, size: int) -> Image.Image:
    hue = plugin_cover_hue(seed)
    base = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(base)
    draw.rounded_rectangle((0, 0, size, size), radius=max(8, size // 5), fill=_hsl_to_rgb(hue, 0.42, 0.58))
    label = _fallback_label(seed)
    font = help_font(max(18, size // 2))
    bbox = draw.textbbox((0, 0), label, font=font)
    tw = bbox[2] - bbox[0]
    th = bbox[3] - bbox[1]
    draw.text(((size - tw) / 2, (size - th) / 2 - 2), label, fill=(255, 255, 255, 245), font=font)
    return base


def _fallback_label(seed: str) -> str:
    text = re.sub(r"\s+", "", seed or "牛")
    if not text:
        return "牛"
    ch = text[0]
    if "\u4e00" <= ch <= "\u9fff":
        return ch
    return ch.upper()


def _hsl_to_rgb(h: int, s: float, lightness: float) -> tuple[int, int, int]:
    h = h % 360
    c = (1 - abs(2 * lightness - 1)) * s
    x = c * (1 - abs((h / 60) % 2 - 1))
    m = lightness - c / 2
    if h < 60:
        r, g, b = c, x, 0
    elif h < 120:
        r, g, b = x, c, 0
    elif h < 180:
        r, g, b = 0, c, x
    elif h < 240:
        r, g, b = 0, x, c
    elif h < 300:
        r, g, b = x, 0, c
    else:
        r, g, b = c, 0, x
    return (int((r + m) * 255), int((g + m) * 255), int((b + m) * 255))


def load_help_plugin_icon(plugin: Any, *, size: int, label: str) -> Image.Image:
    path = resolve_help_icon_path(plugin)
    if path is not None:
        try:
            with Image.open(path) as opened:
                return rounded_image(opened, size, max(8, size // 5))
        except OSError:
            pass
    brand = load_brand_avatar_icon(size)
    if brand is not None:
        return brand
    return fallback_icon_image(label, size)
