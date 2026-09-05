"""磁盘插件包发现与来源判定。"""

from __future__ import annotations

from pathlib import Path  # noqa: TC003

from pallas.console.webui import plugin_catalog as _repo
from pallas.core.platform.bot_runtime.plugin_matrix import (
    is_bundled_play_plugin,
    is_core_plugin,
    is_extra_plugin,
)

_INFRA_NAME_PREFIXES = (
    "nonebot",
    "nonebot_plugin",
    "nonebot-plugin",
    "uniseg",
)

_INFRA_EXACT = frozenset({
    "nonebot_plugin_waiter",
    "nonebot_plugin_apscheduler",
    "nonebot-plugin-apscheduler",
    "nonebot-plugin-alconna",
    "nonebot_plugin_alconna",
})


def discover_plugin_packages() -> list[str]:
    if not _repo._PLUGINS_ROOT.is_dir():
        return []
    out: list[str] = []
    for entry in sorted(_repo._PLUGINS_ROOT.iterdir()):
        if not entry.is_dir() or entry.name.startswith("."):
            continue
        if entry.name.startswith("_"):
            continue
        if not (entry / "__init__.py").is_file():
            continue
        out.append(entry.name)
    return out


def discover_pyproject_plugin_modules() -> list[str]:
    """pyproject [tool.nonebot.plugins] 声明的 pip/外部模块。"""
    from pallas.core.platform.bot_runtime.pyproject_plugins import parse_nonebot_plugin_config

    modules, _dirs = parse_nonebot_plugin_config()
    return list(modules)


def discover_extra_plugin_packages() -> dict[str, Path]:
    """站点 ``extra_plugin_dirs`` 下的插件包：目录名 → 包根路径。"""
    from pallas.core.foundation.config.repo_settings import resolve_extra_plugin_dirs

    out: dict[str, Path] = {}
    for rel in resolve_extra_plugin_dirs():
        root = (_repo.PROJECT_ROOT / rel).resolve()
        if not root.is_dir():
            continue
        for entry in sorted(root.iterdir()):
            if not entry.is_dir() or entry.name.startswith("."):
                continue
            if not (entry / "__init__.py").is_file():
                continue
            out[entry.name] = entry
    return out


def plugin_source_from_module_path(mod_file: str) -> str | None:
    if not mod_file:
        return None
    try:
        rel = Path(mod_file).resolve().relative_to(_repo.PROJECT_ROOT.resolve()).as_posix()
    except ValueError:
        return "pip"
    if rel.startswith("local/"):
        return "local"
    if rel.startswith("packages/"):
        package = rel.removeprefix("packages/").split("/", 1)[0]
        if is_core_plugin(package):
            return "core"
        if is_extra_plugin(package):
            return "extra"
        if is_bundled_play_plugin(package):
            return "bundled"
        return "core"
    return "pip"


def module_dir_rel(mod_file: str) -> str | None:
    if not mod_file:
        return None
    try:
        return Path(mod_file).resolve().parent.relative_to(_repo.PROJECT_ROOT.resolve()).as_posix()
    except (ValueError, OSError):
        return None


def infer_plugin_source(
    package: str,
    loaded: object | None,
    *,
    extra_pkgs: dict[str, Path],
) -> tuple[_repo.PluginSourceKind, str | None]:
    if loaded is not None:
        mod = getattr(loaded, "module", None)
        module_name = getattr(mod, "__name__", "") if mod is not None else ""
        file_path = getattr(mod, "__file__", "") if mod is not None else ""
        src = plugin_source_from_module_path(file_path)
        if src == "local":
            return "local", module_dir_rel(file_path) or _package_dir_posix(extra_pkgs.get(package))
        if src in ("core", "extra", "bundled"):
            return src, module_dir_rel(file_path) or f"packages/{package}"
        if src == "pip":
            if is_extra_plugin(package):
                bundled_root = _repo._PLUGINS_ROOT / package
                bundled_dir = f"packages/{package}" if (bundled_root / "__init__.py").is_file() else None
                return "extra", bundled_dir
            return "pip", None
        if module_name.startswith("packages."):
            if is_extra_plugin(package):
                return "extra", f"packages/{package}"
            if is_bundled_play_plugin(package):
                return "bundled", f"packages/{package}"
            return "core", f"packages/{package}"
        if extra_pkgs.get(package) is not None:
            return "local", _package_dir_posix(extra_pkgs.get(package))
    local_root = extra_pkgs.get(package)
    if local_root is not None:
        return "local", _package_dir_posix(local_root)
    if (_repo._PLUGINS_ROOT / package / "__init__.py").is_file():
        if is_extra_plugin(package):
            return "extra", f"packages/{package}"
        if is_bundled_play_plugin(package):
            return "bundled", f"packages/{package}"
        return "core", f"packages/{package}"
    return "pip", None


def _package_dir_posix(path: Path | None) -> str | None:
    if path is None:
        return None
    try:
        return path.resolve().relative_to(_repo.PROJECT_ROOT.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def is_infrastructure_plugin_name(name: str, module_name: str) -> bool:
    n = (name or "").strip().lower()
    m = (module_name or "").strip().lower()
    if n in _INFRA_EXACT or m in _INFRA_EXACT:
        return True
    return any(n.startswith(p) or m.startswith(p) for p in _INFRA_NAME_PREFIXES)
