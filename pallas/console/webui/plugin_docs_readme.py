"""从主仓 docs/plugins 读取已加载插件的 bundled README。"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from pallas.core.foundation.paths import PROJECT_ROOT

if TYPE_CHECKING:
    from pathlib import Path

_BRAND_AVATAR_HTML = re.compile(
    r'(<img\b[^>]*\bsrc=["\'])/pallas/assets/brand-avatar(?:-hd)?\.png(["\'])',
    re.IGNORECASE,
)
_BRAND_AVATAR_MD = re.compile(
    r"(!\[[^\]]*]\()/pallas/assets/brand-avatar(?:-hd)?\.png(\))",
    re.IGNORECASE,
)
_PLUGIN_ASSETS = re.compile(
    r'(!\[[^\]]*]\(|<img\b[^>]*\bsrc=["\'])(?:\./)?assets/',
    re.IGNORECASE,
)


def bundled_plugin_readme_relative_path(plugin_id: str) -> str | None:
    from pallas.core.platform.bot_runtime.plugin_matrix import (
        OFFICIAL_EXTENSION_README_PATHS,
        extra_package_for_plugin,
    )
    from pallas.core.platform.bot_runtime.plugin_package_aliases import canonical_plugin_package

    clean = canonical_plugin_package((plugin_id or "").strip())
    if not clean:
        return None

    pkg = extra_package_for_plugin(clean)
    if pkg:
        rel = OFFICIAL_EXTENSION_README_PATHS.get(pkg)
        if rel and (PROJECT_ROOT / rel).is_file():
            return rel

    candidates: list[str] = []
    for candidate in (clean, (plugin_id or "").strip()):
        if candidate and candidate not in candidates:
            candidates.append(candidate)
    for candidate in candidates:
        rel = f"docs/plugins/{candidate}/README.md"
        if (PROJECT_ROOT / rel).is_file():
            return rel
    return None


def resolve_bundled_readme_hero_image_url(plugin_id: str, plugin_root: Path | None = None) -> str | None:
    """bundled README 顶图：优先包内 cover，官方扩展再回退扩展仓 brand-avatar。"""
    from pallas.console.webui.plugin_package_assets import (
        plugin_roots_for_id,
        resolve_plugin_package_visual_urls,
    )
    from pallas.core.platform.bot_runtime.plugin_matrix import (
        OFFICIAL_EXTENSION_REPOS,
        extra_package_for_plugin,
        official_extension_cover,
    )

    pid = canonical_plugin_id(plugin_id)
    if not pid:
        return None

    roots = plugin_roots_for_id(pid)
    root = plugin_root or (roots[0] if roots else None)
    cover_url = resolve_plugin_package_visual_urls(plugin_id=pid, plugin_root=root).get("cover")
    if cover_url:
        return cover_url

    package = extra_package_for_plugin(pid)
    if package and package in OFFICIAL_EXTENSION_REPOS:
        return official_extension_cover(package)
    return None


def normalize_bundled_plugin_readme_markdown(plugin_id: str, markdown: str) -> str:
    """改写 bundled README 资源路径；包内 cover 或官方扩展顶图替换 brand-avatar 占位。"""
    pid = canonical_plugin_id(plugin_id)
    out = (markdown or "").replace("../assets/", "/pallas/assets/").replace("docs/assets/", "/pallas/assets/")
    if not pid:
        return out

    asset_prefix = f"/pallas/plugin-assets/{pid}/"
    out = _PLUGIN_ASSETS.sub(rf"\1{asset_prefix}assets/", out)

    from pallas.console.webui.plugin_package_assets import plugin_roots_for_id

    roots = plugin_roots_for_id(pid)
    root = roots[0] if roots else None
    hero_image_url = resolve_bundled_readme_hero_image_url(pid, root)
    if not hero_image_url:
        return out

    out, html_n = _BRAND_AVATAR_HTML.subn(rf"\1{hero_image_url}\2", out, count=1)
    if html_n:
        return out
    out, _ = _BRAND_AVATAR_MD.subn(rf"\1{hero_image_url}\2", out, count=1)
    return out


def read_bundled_plugin_readme(plugin_id: str) -> dict[str, str] | None:
    rel = bundled_plugin_readme_relative_path(plugin_id)
    if not rel:
        return None
    try:
        markdown = (PROJECT_ROOT / rel).read_text(encoding="utf-8")
    except OSError:
        return None
    if not markdown.strip():
        return None
    clean = canonical_plugin_id(plugin_id)
    return {
        "plugin": clean,
        "relative_path": rel,
        "markdown": normalize_bundled_plugin_readme_markdown(clean, markdown),
        "source": "bundled",
    }


def canonical_plugin_id(plugin_id: str) -> str:
    from pallas.core.platform.bot_runtime.plugin_package_aliases import canonical_plugin_package

    return canonical_plugin_package((plugin_id or "").strip())
