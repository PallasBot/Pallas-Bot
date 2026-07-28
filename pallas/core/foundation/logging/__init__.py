"""与 NoneBot / loguru 衔接的日志集成。"""

from .bridge import (
    apply_stdlib_logging_channel_prefix,
    configure_quiet_library_loggers,
    install_startup_log_noise_patcher,
    is_matcher_lifecycle_noise,
    resolve_repo_log_level,
)
from .event_log import compact_inbound_event_log, inbound_event_log_as_debug

__all__ = [
    "apply_stdlib_logging_channel_prefix",
    "compact_inbound_event_log",
    "configure_quiet_library_loggers",
    "inbound_event_log_as_debug",
    "install_startup_log_noise_patcher",
    "is_matcher_lifecycle_noise",
    "resolve_repo_log_level",
]
