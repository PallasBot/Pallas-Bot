"""与 NoneBot / loguru 衔接的日志集成。"""

from .bridge import (
    apply_stdlib_logging_channel_prefix,
    configure_quiet_library_loggers,
    install_startup_log_noise_patcher,
    resolve_repo_log_level,
)

__all__ = [
    "apply_stdlib_logging_channel_prefix",
    "configure_quiet_library_loggers",
    "install_startup_log_noise_patcher",
    "resolve_repo_log_level",
]
