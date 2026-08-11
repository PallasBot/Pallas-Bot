"""插件业务事件日志的稳定入口。"""

from pallas.core.foundation.logging.bridge import format_plugin_event
from pallas.core.foundation.startup_report import register_plugin_startup_ready

__all__ = ["format_plugin_event", "register_plugin_startup_ready"]
