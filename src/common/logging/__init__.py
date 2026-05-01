"""与 NoneBot / loguru 衔接的日志集成（入口模块）。"""

from .bridge import apply_stdlib_logging_channel_prefix

__all__ = ["apply_stdlib_logging_channel_prefix"]
