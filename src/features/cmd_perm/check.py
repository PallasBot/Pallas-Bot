"""运行时权限：等级语义见 registry。"""

from __future__ import annotations

from nonebot.adapters import Bot  # noqa: TC002
from nonebot.adapters.onebot.v11 import GroupMessageEvent, MessageEvent, PrivateMessageEvent, permission
from nonebot.internal.adapter import Event  # noqa: TC002
from nonebot.permission import SUPERUSER, Permission

from src.foundation.config import user_is_admin_of_any_bot, user_is_bot_admin

from .config import get_cmd_perm_config
from .registry import resolved_level


async def satisfies_command_permission(bot: Bot, event: Event, command_id: str) -> bool:
    if not isinstance(event, MessageEvent):
        return False
    cfg = get_cmd_perm_config()
    level = resolved_level(command_id, cfg.command_permission_overrides)
    su = await SUPERUSER(bot, event)
    if level == "everyone":
        return True
    if level == "superuser":
        return su
    if su:
        return True
    try:
        uid = int(event.get_user_id())
        sid = int(event.self_id)
    except Exception:
        return False

    async def bot_ok() -> bool:
        try:
            return await user_is_bot_admin(sid, uid) or await user_is_admin_of_any_bot(uid)
        except Exception as exc:
            from src.foundation.db.pool_budget import is_pg_pool_timeout_error

            if is_pg_pool_timeout_error(exc):
                return False
            raise

    if level == "bot_moderator":
        return await bot_ok()
    go = ga = False
    if isinstance(event, GroupMessageEvent):
        go = await permission.GROUP_OWNER(bot, event)
        ga = await permission.GROUP_ADMIN(bot, event)
    is_oa = go or ga
    if level == "group_moderator":
        if isinstance(event, PrivateMessageEvent):
            return await bot_ok()
        return is_oa
    if level == "staff":
        if isinstance(event, GroupMessageEvent):
            if is_oa:
                return True
            return await bot_ok()
        if await bot_ok():
            return True
        return False
    return False


def permission_for_command(command_id: str) -> Permission:
    async def _checker(bot: Bot, event: Event) -> bool:
        return await satisfies_command_permission(bot, event, command_id)

    return Permission(_checker)


def group_message_permission_for_command(command_id: str) -> Permission:
    """OneBot V11 群消息 + 可配置命令权限。NoneBot 禁止 `Permission & Permission`，故合并为单 checker。"""
    inner = permission_for_command(command_id)

    async def _checker(bot: Bot, event: Event) -> bool:
        if not await permission.GROUP(bot, event):
            return False
        return await inner(bot, event)

    return Permission(_checker)


def group_or_private_message_permission_for_command(command_id: str) -> Permission:
    """OneBot V11 群或私聊 + 可配置命令权限。"""
    inner = permission_for_command(command_id)

    async def _checker(bot: Bot, event: Event) -> bool:
        is_group = await permission.GROUP(bot, event)
        is_private = await permission.PRIVATE(bot, event)
        if not (is_group or is_private):
            return False
        return await inner(bot, event)

    return Permission(_checker)


def private_message_permission_for_command(command_id: str) -> Permission:
    """OneBot V11 私聊消息 + 可配置命令权限。"""
    inner = permission_for_command(command_id)

    async def _checker(bot: Bot, event: Event) -> bool:
        if not await permission.PRIVATE(bot, event):
            return False
        return await inner(bot, event)

    return Permission(_checker)
