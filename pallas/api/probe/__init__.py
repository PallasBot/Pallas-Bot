"""网关/服务连通探测结果类型与格式化；供插件 WebUI 健康页使用。"""

from pallas.core.shared.service_probe import (
    ServiceProbeResult,
    format_probe_lines,
    format_probe_text,
)

__all__ = [
    "ServiceProbeResult",
    "format_probe_lines",
    "format_probe_text",
]
