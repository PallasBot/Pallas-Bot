"""群内口令（牛牛 + 动词）。"""

from src.foundation.command_prefix import matches_command_prefix

CMD_OPEN = "牛牛卧底"
CMD_JOIN = "牛牛加入"
CMD_QUIT = "牛牛退出"
CMD_START = "牛牛发身份"
CMD_VOTE = "牛牛投票"
CMD_STATUS = "牛牛局势"
CMD_END = "牛牛结束"

SPY_GROUP_COMMAND_PREFIXES = (
    CMD_OPEN,
    "牛牛谁是卧底",
    CMD_JOIN,
    CMD_QUIT,
    CMD_START,
    "牛牛开始",
    CMD_VOTE,
    CMD_STATUS,
    CMD_END,
)


def is_spy_group_command(plaintext: str) -> bool:
    text = (plaintext or "").strip()
    if not text:
        return False
    return any(matches_command_prefix(text, cmd) for cmd in SPY_GROUP_COMMAND_PREFIXES)
