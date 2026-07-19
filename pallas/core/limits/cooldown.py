"""命令冷却：复用 foundation 配置存储，统一 key 前缀。"""

from __future__ import annotations

from nonebot.adapters.onebot.v11 import GroupMessageEvent, MessageEvent, PrivateMessageEvent

from pallas.core.foundation.config import BotConfig, GroupConfig
from pallas.core.limits.config import get_command_limits_config
from pallas.core.limits.schema import effective_command_limit_for

LIMIT_KEY_PREFIX = "cmd_limit"


def command_limit_action_key(command_id: str) -> str:
    return f"{LIMIT_KEY_PREFIX}:{command_id.strip()}"


def config_for_message_event(event: MessageEvent, cd_sec: int) -> GroupConfig | BotConfig:
    if cd_sec < 1:
        raise ValueError("cd_sec 须 >= 1")
    if isinstance(event, GroupMessageEvent):
        return GroupConfig(event.group_id, cooldown=cd_sec)
    if isinstance(event, PrivateMessageEvent):
        return BotConfig(int(event.self_id), int(event.get_user_id()), cooldown=cd_sec)
    raise TypeError("仅支持群消息或私聊消息事件")


def get_command_cooldown_sec(command_id: str, default_cd_sec: int | None = None) -> int | None:
    cfg = get_command_limits_config()
    cd_sec = effective_command_limit_for(command_id, cfg.command_limit_overrides)
    if cd_sec is not None:
        return cd_sec
    return default_cd_sec


async def is_command_cooldown_ready(
    event: MessageEvent, command_id: str, cd_sec: int | None = None, *, default_cd_sec: int | None = None
) -> bool:
    effective_cd = cd_sec if cd_sec is not None else get_command_cooldown_sec(command_id, default_cd_sec)
    if effective_cd is None:
        raise ValueError(f"命令 {command_id} 未声明默认冷却，且未显式传入 cd_sec")
    if effective_cd <= 0:
        return True
    cfg = config_for_message_event(event, effective_cd)
    return await cfg.is_cooldown(command_limit_action_key(command_id))


async def refresh_command_cooldown(
    event: MessageEvent, command_id: str, cd_sec: int | None = None, *, default_cd_sec: int | None = None
) -> None:
    effective_cd = cd_sec if cd_sec is not None else get_command_cooldown_sec(command_id, default_cd_sec)
    if effective_cd is None:
        raise ValueError(f"命令 {command_id} 未声明默认冷却，且未显式传入 cd_sec")
    if effective_cd <= 0:
        return
    cfg = config_for_message_event(event, effective_cd)
    await cfg.refresh_cooldown(command_limit_action_key(command_id))
