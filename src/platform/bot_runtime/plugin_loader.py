"""按角色加载 NoneBot 插件。"""

from __future__ import annotations

import importlib.util

import nonebot
from nonebot import logger

from src.foundation.apscheduler_runtime import register_apscheduler_startup_hook
from src.foundation.config.repo_settings import read_bootstrap_extra_plugin_dirs
from src.foundation.paths import PROJECT_ROOT
from src.platform.bot_runtime.load_policy import merge_startup_skip_plugins
from src.platform.bot_runtime.pyproject_plugins import (
    extra_plugin_dirs_for_role,
    parse_nonebot_plugin_config,
)
from src.platform.bot_runtime.roles import (
    HUB_PLUGIN_MODULES,
    UNIFIED_SKIP_PLUGIN_NAMES,
    WORKER_SKIP_PLUGIN_NAMES,
    is_hub_role,
    is_unified_role,
)

_PLUGINS_ROOT = PROJECT_ROOT / "src" / "plugins"
_PYPROJECT = PROJECT_ROOT / "pyproject.toml"
_APSCHEDULER_MODULE = "nonebot_plugin_apscheduler"


def _discover_plugin_modules() -> list[str]:
    names: list[str] = []
    if not _PLUGINS_ROOT.is_dir():
        return names
    for entry in sorted(_PLUGINS_ROOT.iterdir()):
        if not entry.is_dir():
            continue
        if entry.name.startswith("_"):
            continue
        if not (entry / "__init__.py").is_file():
            continue
        names.append(f"src.plugins.{entry.name}")
    return names


def _short_name(module_path: str) -> str:
    return module_path.rsplit(".", 1)[-1]


def _prioritize_scheduler_modules(module_paths: list[str]) -> list[str]:
    """nonebot_plugin_apscheduler 须先于依赖 scheduler 的 src 插件加载。"""
    sched = [m for m in module_paths if _short_name(m) == _APSCHEDULER_MODULE]
    rest = [m for m in module_paths if m not in sched]
    return sched + rest


def load_apscheduler_plugin_first(*, role_label: str, loaded_short: set[str]) -> bool:
    if _short_name(_APSCHEDULER_MODULE) in loaded_short:
        return False
    if _load_plugin_module(_APSCHEDULER_MODULE, role_label=role_label, loaded_short=loaded_short):
        register_apscheduler_startup_hook()
        return True
    return False


def _load_plugin_module(
    module_path: str,
    *,
    role_label: str,
    loaded_short: set[str],
) -> bool:
    short = _short_name(module_path)
    if short in loaded_short:
        return False
    if importlib.util.find_spec(module_path) is None:
        logger.error(
            "bot_runtime: {} skip {} (pip 包未安装，请在仓库根目录执行 uv sync)",
            role_label,
            module_path,
        )
        return False
    try:
        nonebot.load_plugin(module_path)
        loaded_short.add(short)
        return True
    except Exception as e:
        logger.warning("bot_runtime: {} failed to load {}: {}", role_label, module_path, e)
        return False


def _load_toml_module_plugins(
    module_paths: list[str],
    *,
    role_label: str,
    skip_short: frozenset[str],
    loaded_short: set[str],
) -> int:
    return _load_discovered_plugin_modules(
        role_label=role_label,
        module_paths=module_paths,
        skip_short=skip_short,
        loaded_short=loaded_short,
    )


def _load_discovered_plugin_modules(
    *,
    role_label: str,
    module_paths: list[str],
    skip_short: frozenset[str],
    loaded_short: set[str],
    skip_module_paths: frozenset[str] = frozenset(),
) -> int:
    count = 0
    for mod in module_paths:
        short = _short_name(mod)
        if mod in skip_module_paths or short in skip_short or short in loaded_short:
            continue
        if _load_plugin_module(mod, role_label=role_label, loaded_short=loaded_short):
            count += 1
    return count


def _load_toml_extra_plugin_dirs(
    plugin_dirs: list[str],
    *,
    role_label: str,
    loaded_short: set[str],
) -> int:
    count = 0
    for rel_dir in plugin_dirs:
        root = PROJECT_ROOT / rel_dir
        if not root.is_dir():
            logger.warning("bot_runtime: {} plugin_dir missing: {}", role_label, rel_dir)
            continue
        dir_loaded = 0
        entries = sorted(root.iterdir(), key=lambda p: p.name)
        for entry in entries:
            if not entry.is_dir() or entry.name.startswith("."):
                continue
            if not (entry / "__init__.py").is_file():
                continue
            sub_rel = f"{rel_dir.rstrip('/')}/{entry.name}"
            pkg_path = PROJECT_ROOT / sub_rel
            try:
                plugin = nonebot.load_plugin(pkg_path)
                found = [plugin] if plugin is not None else []
            except Exception as e:
                logger.warning(
                    "bot_runtime: {} load_plugin({}) failed: {}",
                    role_label,
                    sub_rel,
                    e,
                )
                continue
            for plugin in found:
                mod = getattr(plugin, "module", None)
                if mod is None:
                    continue
                name = getattr(mod, "__name__", "") or ""
                if name:
                    loaded_short.add(_short_name(name))
            dir_loaded += len(found)
            count += len(found)
        logger.info(
            "bot_runtime: {} load_plugins({}) -> {} plugin(s)",
            role_label,
            rel_dir,
            dir_loaded,
        )
    return count


_INGRESS_GATE_MODULE = "src.plugins.ingress_gate"


def load_ingress_gate_plugin(*, role_label: str, loaded_short: set[str]) -> bool:
    gate_path = _PLUGINS_ROOT / "ingress_gate"
    if not gate_path.is_dir() or not (gate_path / "__init__.py").is_file():
        return False
    return _load_plugin_module(_INGRESS_GATE_MODULE, role_label=role_label, loaded_short=loaded_short)


def _append_bootstrap_plugin_dirs(plugin_dirs: list[str]) -> list[str]:
    out = list(plugin_dirs)
    seen = {d.strip().replace("\\", "/").rstrip("/") for d in out}
    for d in read_bootstrap_extra_plugin_dirs():
        norm = d.strip().replace("\\", "/").rstrip("/")
        if norm and norm not in seen:
            seen.add(norm)
            out.append(d)
    return out


def load_pyproject_extra_plugins(
    *,
    role_label: str,
    skip_short: frozenset[str],
    loaded_short: set[str],
    include_extra_dirs: bool,
    include_bootstrap_dirs: bool = True,
) -> int:
    """加载 pyproject [tool.nonebot.plugins] 与额外 plugin_dirs。"""
    module_paths, plugin_dirs = parse_nonebot_plugin_config(_PYPROJECT)
    module_paths = _prioritize_scheduler_modules(module_paths)
    total = 0
    if include_extra_dirs:
        extra_dirs = extra_plugin_dirs_for_role(plugin_dirs)
        if include_bootstrap_dirs:
            extra_dirs = _append_bootstrap_plugin_dirs(extra_dirs)
        total += _load_toml_extra_plugin_dirs(extra_dirs, role_label=role_label, loaded_short=loaded_short)
    total += _load_toml_module_plugins(
        module_paths,
        role_label=role_label,
        skip_short=skip_short,
        loaded_short=loaded_short,
    )
    return total


def load_plugins_for_role() -> None:
    from src.platform.bot_runtime.ingress_dispatch_runtime import register_ingress_dispatch_runtime

    if not is_hub_role():
        register_ingress_dispatch_runtime()

    if is_unified_role():
        loaded_short: set[str] = set()
        load_apscheduler_plugin_first(role_label="unified", loaded_short=loaded_short)
        load_ingress_gate_plugin(role_label="unified", loaded_short=loaded_short)

        bootstrap_dirs = read_bootstrap_extra_plugin_dirs()
        bootstrap_loaded = 0
        if bootstrap_dirs:
            bootstrap_loaded = _load_toml_extra_plugin_dirs(
                bootstrap_dirs,
                role_label="unified",
                loaded_short=loaded_short,
            )

        unified_skip = merge_startup_skip_plugins(UNIFIED_SKIP_PLUGIN_NAMES)
        loaded = _load_discovered_plugin_modules(
            role_label="unified",
            module_paths=_discover_plugin_modules(),
            skip_short=unified_skip,
            skip_module_paths=frozenset({_INGRESS_GATE_MODULE}),
            loaded_short=loaded_short,
        )

        extra = load_pyproject_extra_plugins(
            role_label="unified",
            skip_short=unified_skip,
            loaded_short=loaded_short,
            include_extra_dirs=True,
            include_bootstrap_dirs=False,
        )
        logger.info(
            "bot_runtime: role=unified, local_plugins={} src_plugins={} pyproject_extra={} skip={}",
            bootstrap_loaded,
            loaded,
            extra,
            sorted(unified_skip),
        )
        return

    if not _PLUGINS_ROOT.is_dir():
        nonebot.load_from_toml("pyproject.toml")
        return

    loaded_short: set[str] = set()

    if is_hub_role():
        load_apscheduler_plugin_first(role_label="hub", loaded_short=loaded_short)
        bootstrap_dirs = read_bootstrap_extra_plugin_dirs()
        bootstrap_loaded = 0
        if bootstrap_dirs:
            bootstrap_loaded = _load_toml_extra_plugin_dirs(
                bootstrap_dirs,
                role_label="hub",
                loaded_short=loaded_short,
            )
        loaded = _load_discovered_plugin_modules(
            role_label="hub",
            module_paths=HUB_PLUGIN_MODULES,
            skip_short=frozenset(),
            loaded_short=loaded_short,
        )
        extra = load_pyproject_extra_plugins(
            role_label="hub",
            skip_short=merge_startup_skip_plugins(WORKER_SKIP_PLUGIN_NAMES),
            loaded_short=loaded_short,
            include_extra_dirs=False,
        )
        logger.info(
            "bot_runtime: role=hub, local_plugins={} loaded {}/{} hub modules, +{} from pyproject.plugins",
            bootstrap_loaded,
            loaded,
            len(HUB_PLUGIN_MODULES),
            extra,
        )
        return

    load_apscheduler_plugin_first(role_label="worker", loaded_short=loaded_short)

    load_ingress_gate_plugin(role_label="worker", loaded_short=loaded_short)

    bootstrap_dirs = read_bootstrap_extra_plugin_dirs()
    bootstrap_loaded = 0
    if bootstrap_dirs:
        bootstrap_loaded = _load_toml_extra_plugin_dirs(
            bootstrap_dirs,
            role_label="worker",
            loaded_short=loaded_short,
        )

    worker_skip = merge_startup_skip_plugins(WORKER_SKIP_PLUGIN_NAMES)

    loaded = _load_discovered_plugin_modules(
        role_label="worker",
        module_paths=_discover_plugin_modules(),
        skip_short=worker_skip,
        skip_module_paths=frozenset({_INGRESS_GATE_MODULE}),
        loaded_short=loaded_short,
    )

    extra = load_pyproject_extra_plugins(
        role_label="worker",
        skip_short=worker_skip,
        loaded_short=loaded_short,
        include_extra_dirs=True,
        include_bootstrap_dirs=False,
    )

    from src.platform.shard.registry.config import get_shard_registry_settings

    s = get_shard_registry_settings()
    logger.info(
        "bot_runtime: role=worker shard_id={} local_plugins={} src_plugins={} pyproject_extra={} skip={}",
        s.shard_id,
        bootstrap_loaded,
        loaded,
        extra,
        sorted(worker_skip),
    )
