"""MAA 插件命令触发与正文前缀匹配。"""

from nonebot.adapters import Event
from nonebot.rule import Rule
from nonebot.typing import T_State

from src.foundation.command_prefix import matches_command_prefix

BIND_COMMAND = "牛牛绑定MAA"
BIND_COMMAND_ALT = "牛牛绑定MAA设备"
STATUS_COMMAND = "牛牛MAA状态"
CLEAR_QUEUE_COMMAND = "牛牛清空MAA队列"
SWITCH_DEVICE_COMMAND = "牛牛切换MAA设备"
DEVICE_ALIAS_COMMAND = "牛牛MAA设备名"
RAW_TASK_COMMAND = "牛牛MAA任务"


def maa_command_rule(*commands: str) -> Rule:
    """``on_message`` 用：任一命令前缀匹配。"""

    cmds = tuple(c.strip() for c in commands if c and c.strip())

    async def _match(event: Event, state: T_State) -> bool:
        del state
        try:
            plain = event.get_plaintext()
        except Exception:
            return False
        return any(matches_command_prefix(plain, c) for c in cmds)

    return Rule(_match)
