"""内核运行时：互聊过滤、入站门控、回调与服务网关口令。"""

from __future__ import annotations

from pallas.core.platform.ai_callback.http import register_ai_callback_http
from pallas.core.platform.ai_callback.llm_tools_http import register_llm_tools_http
from pallas.core.platform.bot_runtime.duplicate_prefix_check import register_duplicate_prefix_startup_check
from pallas.core.platform.bot_runtime.roles import is_hub_role
from pallas.core.platform.multi_bot.bot_filter import register_bot_filter_runtime

_KERNEL_REGISTERED = False


def register_kernel_runtime() -> None:
    global _KERNEL_REGISTERED
    if _KERNEL_REGISTERED:
        return
    register_ai_callback_http()
    register_llm_tools_http()
    if not is_hub_role():
        from pallas.core.platform.bot_runtime.ingress_dispatch_runtime import register_ingress_dispatch_runtime
        from pallas.core.platform.ingress.gate import register_ingress_gate_runtime
        from pallas.product.service_gateways.runtime import register_service_gateways_runtime

        register_bot_filter_runtime()
        register_ingress_gate_runtime()
        register_ingress_dispatch_runtime()
        register_service_gateways_runtime()
        register_duplicate_prefix_startup_check()
    _KERNEL_REGISTERED = True
