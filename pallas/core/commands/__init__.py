"""插件开发 SDK：组合式 matcher + 声明 helper。"""

from pallas.core.perm.declare import command_perm_list, command_perm_row

from .checklist import missing_command_declarations
from .context import PluginHandlerContext
from .declare import command_limit_list, command_limit_row
from .matcher import PluginCommand, bind_alias_handlers, group_command, message_command, private_command

__all__ = [
    "PluginCommand",
    "PluginHandlerContext",
    "bind_alias_handlers",
    "command_limit_list",
    "command_limit_row",
    "command_perm_list",
    "command_perm_row",
    "group_command",
    "message_command",
    "missing_command_declarations",
    "private_command",
]
