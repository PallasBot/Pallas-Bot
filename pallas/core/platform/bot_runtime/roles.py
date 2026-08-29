"""进程角色与插件加载名单。"""

from __future__ import annotations

from typing import TYPE_CHECKING

from pallas.core.platform.bot_runtime.plugin_matrix import PLUGIN_BUNDLED_MODULE_PREFIXES
from pallas.core.platform.shard import context as shard_ctx

if TYPE_CHECKING:
    from pallas.core.platform.shard.registry.config import BotRole

# hub 进程必须加载的 bundled 插件名；模块名统一取自注册表的 bundled 前缀表。
_HUB_PLUGIN_NAMES: tuple[str, ...] = (
    "pb_webui",
    "pb_protocol",
    "relogin_bot",
    "maa_hub",
    "blacklist",
    "help",
    "pb_stats",
)

HUB_PLUGIN_MODULES: tuple[str, ...] = tuple(PLUGIN_BUNDLED_MODULE_PREFIXES[name] for name in _HUB_PLUGIN_NAMES)

WORKER_SKIP_PLUGIN_NAMES: frozenset[str] = frozenset({
    "pb_webui",
    "pb_protocol",
    "pallas_protocol",
    "relogin_bot",
    "maa_hub",
    "pb_stats",
})

UNIFIED_SKIP_PLUGIN_NAMES: frozenset[str] = frozenset({
    "relogin_forward",
    "maa_hub",
})

UNIFIED_CATALOG_HIDDEN_PLUGIN_NAMES: frozenset[str] = UNIFIED_SKIP_PLUGIN_NAMES
UNIFIED_CATALOG_HIDDEN_PLUGIN_NAMES = frozenset({
    *UNIFIED_CATALOG_HIDDEN_PLUGIN_NAMES,
    "ingress_gate",
    "pallas_console_metrics",
})


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
