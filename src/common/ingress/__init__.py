"""分片入站相关运行时配置（WebUI 通用配置 / .env）。"""

from .config import IngressFanoutConfig, clear_ingress_fanout_config_cache, get_ingress_fanout_config

__all__ = [
    "IngressFanoutConfig",
    "clear_ingress_fanout_config_cache",
    "get_ingress_fanout_config",
]
