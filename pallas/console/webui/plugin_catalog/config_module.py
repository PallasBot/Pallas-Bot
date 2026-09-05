"""插件 config.py 定位与隔离加载。"""

from __future__ import annotations

import importlib
import importlib.util
from pathlib import Path

from pallas.console.webui import plugin_catalog as _repo


def _config_py_path_for_package_module(pkg_module: str) -> Path | None:
    """定位插件包的 config.py，不执行其 __init__.py。"""
    if pkg_module.startswith(("packages.", "local.")):
        rel = pkg_module.replace(".", "/")
        candidate = _repo.PROJECT_ROOT / rel / "config.py"
        return candidate if candidate.is_file() else None
    try:
        spec = importlib.util.find_spec(pkg_module)
    except (ImportError, ModuleNotFoundError, ValueError):
        return None
    locations = getattr(spec, "submodule_search_locations", None) if spec is not None else None
    if not locations:
        return None
    candidate = Path(locations[0]) / "config.py"
    return candidate if candidate.is_file() else None


def _load_config_class_isolated(cfg_mod_name: str, config_path: Path) -> type | None:
    """隔离加载 config.py，避免触发插件包 __init__（其 matcher / 路由注册）。"""
    import sys

    isolated_name = f"_pallas_isolated_cfg_{cfg_mod_name.replace('.', '_')}"
    try:
        spec = importlib.util.spec_from_file_location(isolated_name, config_path)
        if spec is None or spec.loader is None:
            return None
        module = importlib.util.module_from_spec(spec)
        sys.modules[isolated_name] = module
        try:
            spec.loader.exec_module(module)
        finally:
            sys.modules.pop(isolated_name, None)
    except Exception:
        return None
    cfg_cls = getattr(module, "Config", None)
    if cfg_cls is None or not isinstance(cfg_cls, type):
        return None
    return cfg_cls


def load_config_class_for_package(package: str) -> type | None:
    import sys

    module_name = _repo.resolve_catalog_plugin_module(package)
    if not module_name:
        return None
    cfg_mod_name = module_name if module_name.endswith(".config") else f"{module_name}.config"
    pkg_module = cfg_mod_name[: -len(".config")]
    # 父包已加载（如 hub 上的 protocol）：直接导入 config 子模块。
    if cfg_mod_name in sys.modules or pkg_module in sys.modules:
        try:
            cfg_mod = importlib.import_module(cfg_mod_name)
        except Exception:
            return None
        cfg_cls = getattr(cfg_mod, "Config", None)
        if cfg_cls is None or not isinstance(cfg_cls, type):
            return None
        return cfg_cls
    # 未加载（如 hub 上 worker-only 的 maa/duel）：隔离加载 config.py，绝不执行插件 __init__。
    config_path = _config_py_path_for_package_module(pkg_module)
    if config_path is None:
        return None
    return _load_config_class_isolated(cfg_mod_name, config_path)


def _package_dir_to_module_id(package_root: Path) -> str:
    rel = package_root.resolve().relative_to(_repo.PROJECT_ROOT.resolve())
    return rel.as_posix().replace("/", ".")


def resolve_catalog_plugin_module(plugin_name: str) -> str | None:
    """按目录名或 NoneBot 插件名解析插件模块路径。"""
    from packages.help.plugin_legacy_names import canonical_plugin_name
    from pallas.core.platform.bot_runtime.plugin_matrix import pip_module_installed
    from pallas.core.platform.plugin_runtime.plugin_identity import canonical_plugin_id, plugin_identity

    target = canonical_plugin_name((plugin_name or "").strip())
    if not target:
        return None
    resolved = canonical_plugin_id(target)
    _, by_package = _repo._loaded_plugin_index()
    for key in (target, resolved):
        p = by_package.get(key)
        if p is not None:
            mod = getattr(p, "module", None)
            return getattr(mod, "__name__", "") if mod is not None else None
    extra_pkgs = _repo.discover_extra_plugin_packages()
    for key in (target, resolved):
        if key in extra_pkgs:
            return _package_dir_to_module_id(extra_pkgs[key])
    for key in (target, resolved):
        if (_repo._PLUGINS_ROOT / key / "__init__.py").is_file():
            return f"packages.{key}"
    try:
        ident = plugin_identity(resolved)
        pip_mod = ident.pip_module_prefix
        if pip_mod and pip_module_installed(pip_mod):
            return pip_mod
    except KeyError:
        pass
    return None


def package_has_config_module(package: str, *, package_root: Path | None = None) -> bool:
    if package_root is not None:
        root = package_root
    else:
        root = _repo._PLUGINS_ROOT / package
    return (root / "config.py").is_file()


def module_has_config_module(module_name: str) -> bool:
    if not module_name:
        return False
    try:
        spec = importlib.util.find_spec(f"{module_name}.config")
    except (ImportError, ModuleNotFoundError, ValueError):
        return False
    return spec is not None
