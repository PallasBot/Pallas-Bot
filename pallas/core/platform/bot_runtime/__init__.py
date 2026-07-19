"""按角色加载 NoneBot 插件。"""

from pallas.core.platform.bot_runtime.ingress_dispatch_runtime import (
    ingress_dispatch_runtime_registered,
    register_ingress_dispatch_runtime,
)
from pallas.core.platform.bot_runtime.plugin_loader import load_plugins_for_role
from pallas.core.platform.bot_runtime.roles import (
    bot_role,
    hub_plugin_modules,
    is_hub_role,
    is_sharded_hub,
    is_sharded_worker,
    is_unified_role,
    unified_skip_plugin_names,
    worker_skip_plugin_names,
)

__all__ = [
    "bot_role",
    "hub_plugin_modules",
    "ingress_dispatch_runtime_registered",
    "is_hub_role",
    "is_sharded_hub",
    "is_sharded_worker",
    "is_unified_role",
    "load_plugins_for_role",
    "register_ingress_dispatch_runtime",
    "unified_skip_plugin_names",
    "worker_skip_plugin_names",
]
