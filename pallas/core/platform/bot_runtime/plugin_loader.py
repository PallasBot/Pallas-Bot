"""按角色加载 NoneBot 插件。"""

from __future__ import annotations

import importlib
import importlib.util
import json
import subprocess
import sys
import time
from operator import itemgetter
from typing import TYPE_CHECKING

import nonebot
from nonebot import logger

if TYPE_CHECKING:
    from pathlib import Path

from pallas.core.foundation.apscheduler_runtime import register_apscheduler_startup_hook
from pallas.core.foundation.config.repo_settings import (
    AUTO_LOCAL_PLUGINS_DIR,
    normalize_load_bundled_extra_mode,
    resolve_extra_plugin_dirs,
)
from pallas.core.foundation.paths import PROJECT_ROOT
from pallas.core.foundation.startup_report import register_startup_fact
from pallas.core.platform.bot_runtime.load_policy import merge_startup_skip_plugins
from pallas.core.platform.bot_runtime.plugin_matrix import (
    installed_extra_plugin_modules,
    resolve_hub_bundled_module_paths,
    should_load_bundled_plugin,
)
from pallas.core.platform.bot_runtime.pyproject_plugins import (
    extra_plugin_dirs_for_role,
    parse_nonebot_plugin_config,
)
from pallas.core.platform.bot_runtime.roles import (
    UNIFIED_SKIP_PLUGIN_NAMES,
    WORKER_SKIP_PLUGIN_NAMES,
    is_hub_role,
    is_unified_role,
)

_PLUGINS_ROOT = PROJECT_ROOT / "packages"
_PYPROJECT = PROJECT_ROOT / "pyproject.toml"
_APSCHEDULER_MODULE = "nonebot_plugin_apscheduler"
_BUNDLED_PLUGIN_ENTRY_SUBMODULES: dict[str, tuple[str, ...]] = {}
_PLUGIN_LOAD_SLOW_SECONDS = 1.0
_PLUGIN_LOAD_DIAGNOSTIC_LIMIT = 3
_startup_plugin_load_failures: list[str] = []
_startup_plugin_load_slow: list[tuple[str, float]] = []


def reset_startup_plugin_load_diagnostics() -> None:
    _startup_plugin_load_failures.clear()
    _startup_plugin_load_slow.clear()


def _plugin_display_name(module_path: str) -> str:
    return module_path.replace("\\", "/").rstrip("/").rsplit("/", 1)[-1].rsplit(".", 1)[-1]


def record_startup_plugin_load_failure(module_path: str) -> None:
    _startup_plugin_load_failures.append(_plugin_display_name(module_path))


def record_startup_plugin_load_success(module_path: str, *, elapsed_sec: float) -> None:
    if elapsed_sec >= _PLUGIN_LOAD_SLOW_SECONDS:
        _startup_plugin_load_slow.append((_plugin_display_name(module_path), elapsed_sec))


def startup_plugin_load_diagnostic_facts() -> dict[str, str]:
    facts: dict[str, str] = {}
    if _startup_plugin_load_failures:
        names = _startup_plugin_load_failures[:_PLUGIN_LOAD_DIAGNOSTIC_LIMIT]
        if remaining := len(_startup_plugin_load_failures) - len(names):
            names.append(f"+{remaining}")
        facts["plugin_failures"] = ",".join(names)
    if _startup_plugin_load_slow:
        entries = sorted(_startup_plugin_load_slow, key=itemgetter(1), reverse=True)
        selected = entries[:_PLUGIN_LOAD_DIAGNOSTIC_LIMIT]
        values = [f"{name}={elapsed:.2f}" for name, elapsed in selected]
        if remaining := len(entries) - len(selected):
            values.append(f"+{remaining}")
        facts["plugin_slow"] = ",".join(values)
    return facts


def register_startup_plugin_load_diagnostics() -> None:
    for key, value in startup_plugin_load_diagnostic_facts().items():
        register_startup_fact(key, value)


def _discover_plugin_modules(*, load_bundled_extra: bool | str | None = None) -> list[str]:
    names: list[str] = []
    if not _PLUGINS_ROOT.is_dir():
        return names
    mode = normalize_load_bundled_extra_mode(load_bundled_extra)
    for entry in sorted(_PLUGINS_ROOT.iterdir()):
        if not entry.is_dir():
            continue
        if entry.name.startswith("_"):
            continue
        if not (entry / "__init__.py").is_file():
            continue
        if not should_load_bundled_plugin(entry.name, load_bundled_extra=mode):
            continue
        names.append(f"packages.{entry.name}")
    return names


def _short_name(module_path: str) -> str:
    return module_path.rsplit(".", 1)[-1]


def split_site_local_plugin_dirs(plugin_dirs: list[str]) -> tuple[list[str], list[str]]:
    site_local: list[str] = []
    custom: list[str] = []
    community_dir = AUTO_LOCAL_PLUGINS_DIR.replace("\\", "/").rstrip("/")
    for plugin_dir in plugin_dirs:
        normalized = plugin_dir.strip().replace("\\", "/").rstrip("/").removeprefix("./")
        (site_local if normalized == community_dir else custom).append(plugin_dir)
    return site_local, custom


def plugin_directory_git_origin(plugin_dir: Path) -> str:
    try:
        result = subprocess.run(
            ["git", "remote", "get-url", "origin"],
            cwd=plugin_dir,
            capture_output=True,
            text=True,
            timeout=2,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return ""
    return result.stdout.strip() if result.returncode == 0 else ""


def is_community_plugin_directory(plugin_dir: Path) -> bool:
    index_path = plugin_dir / "community-index.entry.json"
    try:
        entry = json.loads(index_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        entry = None
    if isinstance(entry, dict):
        plugin_id = str(entry.get("id") or entry.get("plugin_id") or "").strip()
        if plugin_id == plugin_dir.name:
            return True

    origin = plugin_directory_git_origin(plugin_dir).lower().removesuffix(".git")
    return bool(origin and not origin.endswith("github.com/pallasbot/pallas-bot"))


def classify_site_local_plugins(plugin_dirs: list[Path]) -> tuple[int, int]:
    community = sum(is_community_plugin_directory(plugin_dir) for plugin_dir in plugin_dirs)
    return len(plugin_dirs) - community, community


def _load_slot_key(module_path: str) -> str:
    from pallas.core.platform.bot_runtime.plugin_package_aliases import canonical_plugin_package

    return canonical_plugin_package(_short_name(module_path))


def _prioritize_scheduler_modules(module_paths: list[str]) -> list[str]:
    """nonebot_plugin_apscheduler 须先于依赖 scheduler 的外部插件加载。"""
    sched = [m for m in module_paths if _short_name(m) == _APSCHEDULER_MODULE]
    rest = [m for m in module_paths if m not in sched]
    return sched + rest


def clear_poisoned_apscheduler_import(*, role_label: str) -> bool:
    """移除未通过 load_plugin 注册的提前 import，避免 NoneBot 拒绝加载。"""
    existing = sys.modules.get(_APSCHEDULER_MODULE)
    if existing is None or getattr(existing, "__plugin__", None) is not None:
        return False
    logger.warning(
        "启动：{} 检测到 {} 被提前 import，清理后重试 load_plugin",
        role_label,
        _APSCHEDULER_MODULE,
    )
    del sys.modules[_APSCHEDULER_MODULE]
    prefix = f"{_APSCHEDULER_MODULE}."
    for name in list(sys.modules):
        if name.startswith(prefix):
            del sys.modules[name]
    return True


def load_apscheduler_plugin_first(*, role_label: str, loaded_short: set[str]) -> bool:
    if _load_slot_key(_APSCHEDULER_MODULE) in loaded_short:
        return True
    clear_poisoned_apscheduler_import(role_label=role_label)
    if _load_plugin_module(_APSCHEDULER_MODULE, role_label=role_label, loaded_short=loaded_short):
        register_apscheduler_startup_hook()
        return True
    logger.error(
        "启动：{} 无法加载 {}；依赖 scheduler 的插件会报 Cannot load plugin",
        role_label,
        _APSCHEDULER_MODULE,
    )
    return False


def load_bundled_plugin_entry_submodules(module_path: str) -> None:
    """薄化 __init__ 的 bundled 插件：由 loader 导入 matcher / startup 子模块。"""
    if not module_path.startswith("packages."):
        return
    subs = _BUNDLED_PLUGIN_ENTRY_SUBMODULES.get(_short_name(module_path))
    if not subs:
        return
    for sub in subs:
        importlib.import_module(f"{module_path}.{sub}")


def runtime_loaded_short_names() -> set[str]:
    """当前进程已加载插件的 canonical 短名集合（供运行时热加载去重）。"""
    out: set[str] = set()
    try:
        from nonebot import get_loaded_plugins
    except Exception:
        return out
    for plugin in get_loaded_plugins():
        nb = str(getattr(plugin, "name", "") or "").strip()
        if nb:
            out.add(_load_slot_key(nb))
        mod = getattr(plugin, "module", None)
        mname = getattr(mod, "__name__", "") if mod is not None else ""
        if mname:
            out.add(_load_slot_key(mname.rsplit(".", 1)[-1]))
    return out


def hot_load_extra_dir_plugin(plugin_id: str, *, role_label: str = "runtime") -> bool:
    """尝试从 extra_plugin_dirs 热加载单个社区插件（仅首次加载；已加载则跳过）。"""
    pid = (plugin_id or "").strip()
    if not pid:
        return False
    if pid in runtime_loaded_short_names():
        logger.debug("运行时热加载：{} 已加载，跳过", pid)
        return False

    from pallas.core.foundation.config.repo_settings import resolve_extra_plugin_dirs
    from pallas.core.plugin_reload.metadata_index import reload_plugin_metadata_index

    loaded_short = runtime_loaded_short_names()
    load_apscheduler_plugin_first(role_label=role_label, loaded_short=loaded_short)
    if _load_slot_key(pid) in loaded_short:
        logger.debug("运行时热加载：{} 同名槽位已占用", pid)
        return False

    for rel_dir in resolve_extra_plugin_dirs():
        norm = rel_dir.strip().replace("\\", "/").rstrip("/")
        pkg_path = PROJECT_ROOT / norm / pid
        if not (pkg_path / "__init__.py").is_file():
            continue
        try:
            plugin = nonebot.load_plugin(pkg_path)
            found = [plugin] if plugin is not None else []
        except Exception as e:
            logger.warning("运行时热加载：{} 加载 {} 失败: {}", role_label, pkg_path, e)
            continue
        if not found:
            continue
        for loaded in found:
            mod = getattr(loaded, "module", None)
            name = getattr(mod, "__name__", "") if mod is not None else ""
            if name:
                load_bundled_plugin_entry_submodules(name)
        reload_plugin_metadata_index()
        logger.info("运行时热加载：{} 已从 {} 加载", pid, norm)
        return True
    logger.warning("运行时热加载：{} 未在 extra_plugin_dirs 中找到有效包", pid)
    return False


def _load_plugin_module(
    module_path: str,
    *,
    role_label: str,
    loaded_short: set[str],
) -> bool:
    slot = _load_slot_key(module_path)
    if slot in loaded_short:
        return False
    if importlib.util.find_spec(module_path) is None:
        record_startup_plugin_load_failure(module_path)
        logger.error(
            "启动：{} 跳过 {}（未发现模块）",
            role_label,
            module_path,
        )
        return False
    try:
        started_at = time.perf_counter()
        nonebot.load_plugin(module_path)
        load_bundled_plugin_entry_submodules(module_path)
        record_startup_plugin_load_success(module_path, elapsed_sec=time.perf_counter() - started_at)
        loaded_short.add(slot)
        return True
    except Exception as e:
        record_startup_plugin_load_failure(module_path)
        log = logger.error if _short_name(module_path) == _APSCHEDULER_MODULE else logger.warning
        log("启动：{} 加载 {} 失败: {}", role_label, module_path, e)
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
        slot = _load_slot_key(mod)
        if mod in skip_module_paths:
            logger.info("启动：{} 跳过 {}（配置排除）", role_label, mod)
            continue
        if short in skip_short:
            logger.info("启动：{} 跳过 {}（配置禁用）", role_label, mod)
            continue
        if slot in loaded_short:
            logger.info("启动：{} 跳过 {}（同名插件已加载）", role_label, mod)
            continue
        if _load_plugin_module(mod, role_label=role_label, loaded_short=loaded_short):
            count += 1
    return count


def _load_toml_extra_plugin_dirs(
    plugin_dirs: list[str],
    *,
    role_label: str,
    loaded_short: set[str],
    loaded_plugin_dirs: list[Path] | None = None,
) -> int:
    count = 0
    for rel_dir in plugin_dirs:
        root = PROJECT_ROOT / rel_dir
        if not root.is_dir():
            logger.warning("启动：{} 插件目录不存在: {}", role_label, rel_dir)
            continue
        dir_loaded = 0
        entries = sorted(root.iterdir(), key=lambda p: p.name)
        for entry in entries:
            if not entry.is_dir() or entry.name.startswith("."):
                continue
            if not (entry / "__init__.py").is_file():
                continue
            if _load_slot_key(entry.name) in loaded_short:
                sub_rel = f"{rel_dir.rstrip('/')}/{entry.name}"
                logger.info(
                    "启动：{} 跳过 {}（同名插件已加载）",
                    role_label,
                    sub_rel,
                )
                continue
            sub_rel = f"{rel_dir.rstrip('/')}/{entry.name}"
            pkg_path = PROJECT_ROOT / sub_rel
            try:
                started_at = time.perf_counter()
                plugin = nonebot.load_plugin(pkg_path)
                found = [plugin] if plugin is not None else []
            except Exception as e:
                record_startup_plugin_load_failure(sub_rel)
                logger.warning(
                    "启动：{} 加载 {} 失败: {}",
                    role_label,
                    sub_rel,
                    e,
                )
                continue
            if not found:
                record_startup_plugin_load_failure(sub_rel)
                continue
            record_startup_plugin_load_success(sub_rel, elapsed_sec=time.perf_counter() - started_at)
            for plugin in found:
                mod = getattr(plugin, "module", None)
                if mod is None:
                    continue
                name = getattr(mod, "__name__", "") or ""
                if name:
                    loaded_short.add(_load_slot_key(name))
            dir_loaded += len(found)
            count += len(found)
            if loaded_plugin_dirs is not None:
                loaded_plugin_dirs.extend(entry for _ in found)
        logger.debug(
            "启动：{} 目录 {} 加载 {} 个",
            role_label,
            rel_dir,
            dir_loaded,
        )
    return count


def load_extra_plugin_dirs_by_source(
    plugin_dirs: list[str],
    *,
    role_label: str,
    loaded_short: set[str],
) -> tuple[int, int, int]:
    site_local_dirs, custom_dirs = split_site_local_plugin_dirs(plugin_dirs)
    site_local_plugin_dirs: list[Path] = []
    _load_toml_extra_plugin_dirs(
        site_local_dirs,
        role_label=role_label,
        loaded_short=loaded_short,
        loaded_plugin_dirs=site_local_plugin_dirs,
    )
    local, community = classify_site_local_plugins(site_local_plugin_dirs)
    extra = _load_toml_extra_plugin_dirs(custom_dirs, role_label=role_label, loaded_short=loaded_short)
    return local, community, extra


def _append_bootstrap_plugin_dirs(plugin_dirs: list[str]) -> list[str]:
    out = list(plugin_dirs)
    seen = {d.strip().replace("\\", "/").rstrip("/") for d in out}
    for d in resolve_extra_plugin_dirs():
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
) -> tuple[int, int, int, int]:
    """加载 pyproject [tool.nonebot.plugins] 与额外 plugin_dirs。"""
    module_paths, plugin_dirs = parse_nonebot_plugin_config(_PYPROJECT)
    module_paths = _prioritize_scheduler_modules(module_paths)
    local_total = 0
    community_total = 0
    extra_total = 0
    if include_extra_dirs:
        extra_dirs = extra_plugin_dirs_for_role(plugin_dirs)
        if include_bootstrap_dirs:
            extra_dirs = _append_bootstrap_plugin_dirs(extra_dirs)
        local_total, community_total, extra_total = load_extra_plugin_dirs_by_source(
            extra_dirs,
            role_label=role_label,
            loaded_short=loaded_short,
        )
    pypi_total = _load_toml_module_plugins(
        module_paths,
        role_label=role_label,
        skip_short=skip_short,
        loaded_short=loaded_short,
    )
    return pypi_total, local_total, community_total, extra_total


def load_plugins_for_role() -> None:
    from pallas.core.platform.bot_runtime.kernel_runtime import register_kernel_runtime

    reset_startup_plugin_load_diagnostics()
    logger.info("[插件] 载入中...")

    if is_unified_role():
        loaded_short: set[str] = set()
        load_apscheduler_plugin_first(role_label="unified", loaded_short=loaded_short)
        register_kernel_runtime()

        bootstrap_dirs = resolve_extra_plugin_dirs()
        local_loaded = 0
        community_loaded = 0
        extra_dir_loaded = 0
        if bootstrap_dirs:
            local_loaded, community_loaded, extra_dir_loaded = load_extra_plugin_dirs_by_source(
                bootstrap_dirs,
                role_label="unified",
                loaded_short=loaded_short,
            )
        unified_skip = merge_startup_skip_plugins(UNIFIED_SKIP_PLUGIN_NAMES)
        loaded = _load_discovered_plugin_modules(
            role_label="unified",
            module_paths=_discover_plugin_modules(),
            skip_short=unified_skip,
            loaded_short=loaded_short,
        )

        nonebot_extra, local_extra, community_extra, extra_extra = load_pyproject_extra_plugins(
            role_label="unified",
            skip_short=unified_skip,
            loaded_short=loaded_short,
            include_extra_dirs=True,
            include_bootstrap_dirs=False,
        )
        pip_extra = _load_discovered_plugin_modules(
            role_label="unified",
            module_paths=installed_extra_plugin_modules(hub=None),
            skip_short=unified_skip,
            loaded_short=loaded_short,
        )
        register_startup_fact(
            "plugins",
            f"local={local_loaded + local_extra} src={loaded} official={pip_extra} "
            f"nonebot={nonebot_extra} community={community_loaded + community_extra} "
            f"extra={extra_dir_loaded + extra_extra} skip={len(unified_skip)}",
        )
        register_startup_plugin_load_diagnostics()
        logger.debug(
            "启动：unified local={} community={} src={} official={} nonebot={} extra_dirs={} skip={}",
            local_loaded + local_extra,
            community_loaded,
            loaded,
            pip_extra,
            nonebot_extra,
            extra_dir_loaded + extra_extra,
            sorted(unified_skip),
        )
        return

    if not _PLUGINS_ROOT.is_dir():
        loaded_short: set[str] = set()
        role_label = "hub" if is_hub_role() else "worker"
        load_apscheduler_plugin_first(role_label=role_label, loaded_short=loaded_short)
        nonebot.load_from_toml("pyproject.toml")
        return

    loaded_short: set[str] = set()
    role_label = "hub" if is_hub_role() else "worker"
    load_apscheduler_plugin_first(role_label=role_label, loaded_short=loaded_short)
    register_kernel_runtime()

    if is_hub_role():
        bootstrap_dirs = resolve_extra_plugin_dirs()
        local_loaded = 0
        community_loaded = 0
        extra_dir_loaded = 0
        if bootstrap_dirs:
            local_loaded, community_loaded, extra_dir_loaded = load_extra_plugin_dirs_by_source(
                bootstrap_dirs,
                role_label="hub",
                loaded_short=loaded_short,
            )
        loaded = _load_discovered_plugin_modules(
            role_label="hub",
            module_paths=resolve_hub_bundled_module_paths(),
            skip_short=frozenset(),
            loaded_short=loaded_short,
        )
        pip_extra = _load_discovered_plugin_modules(
            role_label="hub",
            module_paths=installed_extra_plugin_modules(hub=True),
            skip_short=frozenset(),
            loaded_short=loaded_short,
        )
        nonebot_extra, local_extra, community_extra, extra_extra = load_pyproject_extra_plugins(
            role_label="hub",
            skip_short=merge_startup_skip_plugins(WORKER_SKIP_PLUGIN_NAMES),
            loaded_short=loaded_short,
            include_extra_dirs=False,
        )
        bundled_total = len(resolve_hub_bundled_module_paths())
        register_startup_fact(
            "plugins",
            f"local={local_loaded + local_extra} modules={loaded}/{bundled_total} official={pip_extra} "
            f"nonebot={nonebot_extra} community={community_loaded + community_extra} "
            f"extra={extra_dir_loaded + extra_extra}",
        )
        register_startup_plugin_load_diagnostics()
        logger.debug(
            "启动：hub local={} community={} modules={}/{} official={} nonebot={} extra_dirs={}",
            local_loaded + local_extra,
            community_loaded,
            loaded,
            bundled_total,
            pip_extra,
            nonebot_extra,
            extra_dir_loaded + extra_extra,
        )
        return

    bootstrap_dirs = resolve_extra_plugin_dirs()
    local_loaded = 0
    community_loaded = 0
    extra_dir_loaded = 0
    if bootstrap_dirs:
        local_loaded, community_loaded, extra_dir_loaded = load_extra_plugin_dirs_by_source(
            bootstrap_dirs,
            role_label="worker",
            loaded_short=loaded_short,
        )
    worker_skip = merge_startup_skip_plugins(WORKER_SKIP_PLUGIN_NAMES)

    loaded = _load_discovered_plugin_modules(
        role_label="worker",
        module_paths=_discover_plugin_modules(),
        skip_short=worker_skip,
        loaded_short=loaded_short,
    )

    nonebot_extra, local_extra, community_extra, extra_extra = load_pyproject_extra_plugins(
        role_label="worker",
        skip_short=worker_skip,
        loaded_short=loaded_short,
        include_extra_dirs=True,
        include_bootstrap_dirs=False,
    )

    pip_extra = _load_discovered_plugin_modules(
        role_label="worker",
        module_paths=installed_extra_plugin_modules(hub=False),
        skip_short=worker_skip,
        loaded_short=loaded_short,
    )

    from pallas.core.platform.shard.registry.config import get_shard_registry_settings

    s = get_shard_registry_settings()
    register_startup_fact(
        "plugins",
        f"local={local_loaded + local_extra} src={loaded} official={pip_extra} "
        f"nonebot={nonebot_extra} community={community_loaded + community_extra} "
        f"extra={extra_dir_loaded + extra_extra} skip={len(worker_skip)}",
    )
    register_startup_plugin_load_diagnostics()
    logger.debug(
        "启动：worker shard={} local={} community={} src={} official={} nonebot={} extra_dirs={} skip={}",
        s.shard_id,
        local_loaded + local_extra,
        community_loaded,
        loaded,
        pip_extra,
        nonebot_extra,
        extra_dir_loaded + extra_extra,
        sorted(worker_skip),
    )
    from pallas.core.platform.shard.worker_console_metrics import register_worker_console_metrics_startup

    register_worker_console_metrics_startup()
