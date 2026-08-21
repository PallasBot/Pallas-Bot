"""与 NoneBot / loguru 衔接的日志集成。"""

from .bridge import (
    apply_stdlib_logging_channel_prefix,
    configure_quiet_library_loggers,
    format_repo_console_log,
    format_repo_file_log,
    install_repo_console_log_format,
    install_startup_log_noise_patcher,
    is_matcher_lifecycle_noise,
    reapply_runtime_log_level,
    register_repo_file_sink,
    resolve_repo_log_level,
)
from .event_log import compact_group_message_log, compact_inbound_event_log, inbound_event_log_as_debug
from .throttle import log_rate_limited

__all__ = [
    "apply_stdlib_logging_channel_prefix",
    "compact_group_message_log",
    "compact_inbound_event_log",
    "configure_quiet_library_loggers",
    "format_repo_console_log",
    "format_repo_file_log",
    "inbound_event_log_as_debug",
    "install_repo_console_log_format",
    "install_startup_log_noise_patcher",
    "is_matcher_lifecycle_noise",
    "log_rate_limited",
    "reapply_runtime_log_level",
    "register_repo_file_sink",
    "resolve_repo_log_level",
]
