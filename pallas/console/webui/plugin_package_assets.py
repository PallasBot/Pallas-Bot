"""插件包内 assets 发现与控制台静态 URL（local / packages / pip 安装目录）。"""

from __future__ import annotations

import hashlib
import re
import time
from pathlib import Path

from pallas.console.webui.community_plugin_assets import (
    AVATAR_CANDIDATE_PATHS,
    COVER_CANDIDATE_PATHS,
    ICON_CANDIDATE_PATHS,
)
from pallas.core.foundation.paths import PROJECT_ROOT

PUBLIC_PREFIX = "/pallas/plugin-assets"
_PLUGIN_ID_RE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
_ALL_CANDIDATE_RELS = frozenset(dict.fromkeys((*COVER_CANDIDATE_PATHS, *ICON_CANDIDATE_PATHS, *AVATAR_CANDIDATE_PATHS)))
PACKAGE_ASSET_CANDIDATE_PATHS = tuple(_ALL_CANDIDATE_RELS)
_PKGVIS_REVISION_TTL_SEC = 300.0
_pkgvis_revision_cache: tuple[float, str] = (0.0, "")


def invalidate_plugin_package_assets_revision() -> None:
    global _pkgvis_revision_cache
    _pkgvis_revision_cache = (0.0, "")


def _iter_plugin_asset_roots() -> list[tuple[str, Path]]:
    """单次收集各插件根目录，避免按插件重复 discover / get_loaded_plugins。"""
    from pallas.console.webui.plugin_catalog import (
        discover_extra_plugin_packages,
        discover_plugin_packages,
        resolved_plugin_identity,
    )

    pairs: list[tuple[str, Path]] = []
    seen: set[str] = set()

    def add(pid: str, path: Path) -> None:
        clean = (pid or "").strip()
        if not clean or not path.is_dir():
            return
        key = str(path.resolve())
        if key in seen:
            return
        seen.add(key)
        pairs.append((clean, path.resolve()))

    extra = discover_extra_plugin_packages()
    plugin_ids = sorted(set(discover_plugin_packages()) | set(extra.keys()))
    for pid in plugin_ids:
        local_root = extra.get(pid)
        if local_root is not None and (local_root / "__init__.py").is_file():
            add(pid, local_root)
        for candidate in (
            PROJECT_ROOT / "packages" / pid,
            PROJECT_ROOT / "local" / "plugins" / pid,
        ):
            if (candidate / "__init__.py").is_file():
                add(pid, candidate)

    try:
        from nonebot import get_loaded_plugins
    except Exception:
        return pairs

    for plugin in get_loaded_plugins():
        mod = getattr(plugin, "module", None)
        module_name = getattr(mod, "__name__", "") if mod is not None else ""
        nb_name = str(getattr(plugin, "name", "") or "")
        pid = resolved_plugin_identity(nb_name, module_name) or module_name.rsplit(".", 1)[-1]
        file_path = getattr(mod, "__file__", "") if mod is not None else ""
        if file_path:
            add(pid, Path(file_path).resolve().parent)
    return pairs


def _asset_stat_part(pid: str, root: Path, rel: str) -> str:
    path = root / rel
    try:
        stat = path.stat()
        return f"{pid}:{rel}:{stat.st_mtime_ns}:{stat.st_size}"
    except OSError:
        return f"{pid}:{rel}:0:0"


def _scan_plugin_package_assets_revision() -> str:
    parts: list[str] = []
    for pid, root in _iter_plugin_asset_roots():
        parts.extend(
            _asset_stat_part(pid, root, rel)
            for rel in (
                find_plugin_package_asset(root, COVER_CANDIDATE_PATHS),
                find_plugin_package_asset(root, ICON_CANDIDATE_PATHS),
                find_plugin_package_asset(root, AVATAR_CANDIDATE_PATHS),
            )
            if rel
        )
    if not parts:
        return "pkgvis=0"
    digest = hashlib.sha256("\n".join(sorted(parts)).encode()).hexdigest()[:16]
    return f"pkgvis={digest}"


def plugin_package_assets_revision(*, force: bool = False) -> str:
    """插件包内视觉 assets 变更摘要，供帮助图等磁盘缓存失效（进程内 TTL 缓存）。"""
    now = time.monotonic()
    global _pkgvis_revision_cache
    cached_at, cached = _pkgvis_revision_cache
    if not force and cached and now - cached_at < _PKGVIS_REVISION_TTL_SEC:
        return cached
    result = _scan_plugin_package_assets_revision()
    _pkgvis_revision_cache = (now, result)
    return result


def find_plugin_package_asset(root: Path, candidates: tuple[str, ...]) -> str | None:
    if not root.is_dir():
        return None
    for rel in candidates:
        if rel not in _ALL_CANDIDATE_RELS:
            continue
        path = root / rel
        if path.is_file():
            return rel
    return None


def plugin_package_asset_public_url(plugin_id: str, rel: str) -> str:
    pid = (plugin_id or "").strip()
    safe_rel = rel.replace("\\", "/").lstrip("/")
    return f"{PUBLIC_PREFIX}/{pid}/{safe_rel}"


def resolve_plugin_package_visual_urls(*, plugin_id: str, plugin_root: Path | None) -> dict[str, str | None]:
    roots: list[Path] = []
    if plugin_root is not None and plugin_root.is_dir():
        roots.append(plugin_root.resolve())
    for root in plugin_roots_for_id(plugin_id):
        resolved = root.resolve()
        if resolved not in roots:
            roots.append(resolved)
    for root in roots:
        cover_rel = find_plugin_package_asset(root, COVER_CANDIDATE_PATHS)
        icon_rel = find_plugin_package_asset(root, ICON_CANDIDATE_PATHS)
        avatar_rel = find_plugin_package_asset(root, AVATAR_CANDIDATE_PATHS)
        if not (cover_rel or icon_rel or avatar_rel):
            continue
        cover = plugin_package_asset_public_url(plugin_id, cover_rel) if cover_rel else None
        icon_only = plugin_package_asset_public_url(plugin_id, icon_rel) if icon_rel else None
        avatar = plugin_package_asset_public_url(plugin_id, avatar_rel) if avatar_rel else None
        display_icon = cover or icon_only or avatar
        return {"cover": cover, "icon": display_icon, "avatar": avatar}
    return {"cover": None, "icon": None, "avatar": None}


def plugin_roots_for_id(plugin_id: str) -> list[Path]:
    from pallas.console.webui.plugin_catalog import discover_extra_plugin_packages, resolved_plugin_identity

    pid = (plugin_id or "").strip()
    if not pid:
        return []
    roots: list[Path] = []
    seen: set[str] = set()

    def add_root(path: Path) -> None:
        key = str(path.resolve())
        if key in seen:
            return
        seen.add(key)
        roots.append(path.resolve())

    extra = discover_extra_plugin_packages()
    if pid in extra and (extra[pid] / "__init__.py").is_file():
        add_root(extra[pid])
    for candidate in (
        PROJECT_ROOT / "packages" / pid,
        PROJECT_ROOT / "local" / "plugins" / pid,
    ):
        if (candidate / "__init__.py").is_file():
            add_root(candidate)

    try:
        from nonebot import get_loaded_plugins
    except Exception:
        return roots

    for plugin in get_loaded_plugins():
        mod = getattr(plugin, "module", None)
        module_name = getattr(mod, "__name__", "") if mod is not None else ""
        nb_name = str(getattr(plugin, "name", "") or "")
        resolved = resolved_plugin_identity(nb_name, module_name)
        if resolved != pid and nb_name != pid and module_name.rsplit(".", 1)[-1] != pid:
            continue
        file_path = getattr(mod, "__file__", "") if mod is not None else ""
        if not file_path:
            continue
        add_root(Path(file_path).resolve().parent)
    return roots


def resolve_plugin_package_asset_file(plugin_id: str, asset_rel: str) -> Path | None:
    pid = (plugin_id or "").strip()
    if not _PLUGIN_ID_RE.fullmatch(pid):
        return None
    rel = asset_rel.replace("\\", "/").lstrip("/")
    if rel not in _ALL_CANDIDATE_RELS:
        return None
    for root in plugin_roots_for_id(pid):
        path = (root / rel).resolve()
        try:
            path.relative_to(root)
        except ValueError:
            continue
        if path.is_file():
            return path
    return None
