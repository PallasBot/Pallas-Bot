"""按 PALLAS_BOT_ROLE 加载插件：hub 保留 WebUI/协议端/relogin，worker 承载牛牛。"""

from src.platform.bot_runtime.ingress_dispatch_runtime import (
    ingress_dispatch_runtime_registered,
    register_ingress_dispatch_runtime,
)
from src.platform.bot_runtime.plugin_loader import load_plugins_for_role
from src.platform.bot_runtime.roles import (
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
