"""进程角色与插件加载名单。"""

from __future__ import annotations

from typing import TYPE_CHECKING

from src.platform.shard import context as shard_ctx

if TYPE_CHECKING:
    from src.platform.shard.registry.config import BotRole

HUB_PLUGIN_MODULES: tuple[str, ...] = (
    "src.plugins.pb_webui",
    "src.plugins.pallas_protocol",
    "src.plugins.relogin_bot",
    "src.plugins.maa_hub",
    "src.plugins.blacklist",
    "src.plugins.help",
    "src.plugins.community_stats",
)

WORKER_SKIP_PLUGIN_NAMES: frozenset[str] = frozenset({
    "pb_webui",
    "pallas_protocol",
    "relogin_bot",
    "maa_hub",
})

UNIFIED_SKIP_PLUGIN_NAMES: frozenset[str] = frozenset({
    "relogin_forward",
    "maa_hub",
})

UNIFIED_CATALOG_HIDDEN_PLUGIN_NAMES: frozenset[str] = UNIFIED_SKIP_PLUGIN_NAMES


def bot_role() -> BotRole:
    return shard_ctx.role()


def is_sharding_active() -> bool:
    return shard_ctx.sharding_active()


def is_unified_role() -> bool:
    return shard_ctx.is_unified_role()


def is_hub_role() -> bool:
    return shard_ctx.is_sharded_hub()


def is_sharded_hub() -> bool:
    return shard_ctx.is_sharded_hub()


def is_sharded_worker() -> bool:
    return shard_ctx.is_sharded_worker()


def hub_plugin_modules() -> tuple[str, ...]:
    return HUB_PLUGIN_MODULES


def worker_skip_plugin_names() -> frozenset[str]:
    return WORKER_SKIP_PLUGIN_NAMES


def unified_skip_plugin_names() -> frozenset[str]:
    return UNIFIED_SKIP_PLUGIN_NAMES


def unified_catalog_hidden_plugin_names() -> frozenset[str]:
    return UNIFIED_CATALOG_HIDDEN_PLUGIN_NAMES
