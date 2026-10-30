"""内核运行时：互聊过滤、入站门控、回调与服务网关命令。"""

from __future__ import annotations

from pallas.core.platform.ai_callback.http import register_ai_callback_http
from pallas.core.platform.bot_runtime.duplicate_prefix_check import register_duplicate_prefix_startup_check
from pallas.core.platform.bot_runtime.roles import is_hub_role
from pallas.core.platform.multi_bot.bot_filter import register_bot_filter_runtime

_KERNEL_REGISTERED = False


def register_kernel_runtime() -> None:
    global _KERNEL_REGISTERED
    if _KERNEL_REGISTERED:
        return
    register_ai_callback_http()
    # 旧 llm tools HTTP 根注册已退役（不是 MaiBot 网关）；不再默认挂载该路由。
    if not is_hub_role():
        from nonebot import get_app

        from pallas.core.platform.bot_runtime.ingress_dispatch_runtime import register_ingress_dispatch_runtime
        from pallas.core.platform.ingress.gate import register_ingress_gate_runtime
        from pallas.core.platform.ingress.message_recorder import bind_message_recorder_lifecycle
        from pallas.product.agent_bridge.config import load_bridge_config
        from pallas.product.agent_bridge.managed_control import register_managed_control_http
        from pallas.product.service_gateways.runtime import register_service_gateways_runtime

        if load_bridge_config().enabled:
            register_managed_control_http(get_app())
        register_bot_filter_runtime()
        register_ingress_gate_runtime()
        bind_message_recorder_lifecycle()
        register_ingress_dispatch_runtime()
        register_service_gateways_runtime()
        register_duplicate_prefix_startup_check()
        from pallas.product.llm.silence_gate import register_silence_gate_runtime

        register_silence_gate_runtime()
    _KERNEL_REGISTERED = True
