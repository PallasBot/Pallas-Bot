"""按角色加载 NoneBot 插件。"""

from __future__ import annotations

import nonebot
from nonebot import logger

from src.common.bot_runtime.roles import (
    HUB_PLUGIN_MODULES,
    WORKER_SKIP_PLUGIN_NAMES,
    is_unified_role,
)
from src.common.paths import PROJECT_ROOT

_PLUGINS_ROOT = PROJECT_ROOT / "src" / "plugins"


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


def load_plugins_for_role() -> None:
    if is_unified_role():
        nonebot.load_from_toml("pyproject.toml")
        logger.info("bot_runtime: role=unified, load_from_toml(all plugins)")
        return

    if not _PLUGINS_ROOT.is_dir():
        nonebot.load_from_toml("pyproject.toml")
        return

    from src.common.bot_runtime.roles import is_hub_role

    if is_hub_role():
        loaded = 0
        for mod in HUB_PLUGIN_MODULES:
            try:
                nonebot.load_plugin(mod)
                loaded += 1
            except Exception as e:
                logger.warning("bot_runtime: hub failed to load {}: {}", mod, e)
        logger.info("bot_runtime: role=hub, loaded {}/{} hub modules", loaded, len(HUB_PLUGIN_MODULES))
        return

    # worker：分片门控优先
    ingress_gate = "src.plugins._ingress_gate"
    gate_path = _PLUGINS_ROOT / "_ingress_gate"
    if gate_path.is_dir() and (gate_path / "__init__.py").is_file():
        try:
            nonebot.load_plugin(ingress_gate)
        except Exception as e:
            logger.warning("bot_runtime: worker ingress_gate load failed: {}", e)

    loaded = 0
    for mod in _discover_plugin_modules():
        short = mod.rsplit(".", 1)[-1]
        if short in WORKER_SKIP_PLUGIN_NAMES:
            continue
        if mod == ingress_gate:
            continue
        try:
            nonebot.load_plugin(mod)
            loaded += 1
        except Exception as e:
            logger.warning("bot_runtime: worker skip load {}: {}", mod, e)
    from src.common.shard.registry.config import get_shard_registry_settings

    s = get_shard_registry_settings()
    logger.info(
        "bot_runtime: role=worker shard_id={} loaded_plugins={} skip={}",
        s.shard_id,
        loaded,
        sorted(WORKER_SKIP_PLUGIN_NAMES),
    )
