"""组合式命令 matcher：权限、冷却与日志标签一次封装。"""

from __future__ import annotations

import inspect
from collections.abc import Awaitable, Callable, Sequence
from typing import Literal

from nonebot import logger, on_command
from nonebot.adapters import Bot  # noqa: TC002
from nonebot.adapters.onebot.v11 import MessageEvent  # noqa: TC002
from nonebot.matcher import Matcher  # noqa: TC002
from nonebot.permission import Permission  # noqa: TC002

from pallas.core.limits import is_command_cooldown_ready, refresh_command_cooldown
from pallas.core.perm import (
    group_message_permission_for_command,
    group_or_private_message_permission_for_command,
    private_message_permission_for_command,
)

from .context import PluginHandlerContext

HandlerFunc = Callable[[PluginHandlerContext], Awaitable[None] | None]
Scene = Literal["group", "private", "both"]


class PluginCommand:
    """单个 on_command matcher 与元数据的绑定。"""

    def __init__(
        self,
        *,
        matcher: Matcher,
        command_id: str,
        default_cd_sec: int | None,
        plugin_tag: str,
        alias_bindings: list[PluginCommand] | None = None,
    ) -> None:
        self.matcher = matcher
        self.command_id = command_id
        self.default_cd_sec = default_cd_sec
        self.plugin_tag = plugin_tag
        self.alias_bindings: list[PluginCommand] = list(alias_bindings or [])

    def handle(self, func: HandlerFunc | None = None) -> Callable[[HandlerFunc], HandlerFunc]:
        def decorator(handler: HandlerFunc) -> HandlerFunc:
            @self.matcher.handle()
            async def _wrapper(bot: Bot, event: MessageEvent) -> None:
                if self.default_cd_sec is not None and self.default_cd_sec > 0:
                    if not await is_command_cooldown_ready(
                        event,
                        self.command_id,
                        default_cd_sec=self.default_cd_sec,
                    ):
                        return
                    await refresh_command_cooldown(
                        event,
                        self.command_id,
                        default_cd_sec=self.default_cd_sec,
                    )
                ctx = PluginHandlerContext(
                    bot=bot,
                    event=event,
                    command_id=self.command_id,
                    matcher=self.matcher,
                    plugin_tag=self.plugin_tag,
                )
                logger.debug("[plugin:{}] command={} user={}", self.plugin_tag, self.command_id, ctx.user_id)
                result = handler(ctx)
                if inspect.isawaitable(result):
                    await result

            return handler

        if func is not None:
            return decorator(func)
        return decorator


def _permission_for_scene(command_id: str, scene: Scene) -> Permission:
    if scene == "group":
        return group_message_permission_for_command(command_id)
    if scene == "private":
        return private_message_permission_for_command(command_id)
    return group_or_private_message_permission_for_command(command_id)


def _plugin_tag_from_command_id(command_id: str) -> str:
    return (command_id.split(".", 1)[0] if command_id else "").strip() or "plugin"


def message_command(
    command_id: str,
    prefix: str,
    *,
    aliases: Sequence[str] = (),
    scene: Scene = "both",
    cd_sec: int | None = 0,
    priority: int = 5,
    block: bool = True,
) -> PluginCommand:
    """注册口令 matcher；``prefix`` 为主命令名，``aliases`` 共享同一 handler 时需多次调用 handle。"""
    primary = (prefix or "").strip()
    if not primary:
        raise ValueError("prefix 不能为空")
    plugin_tag = _plugin_tag_from_command_id(command_id)
    cmd = on_command(
        primary,
        priority=priority,
        block=block,
        permission=_permission_for_scene(command_id, scene),
    )
    binding = PluginCommand(
        matcher=cmd,
        command_id=command_id,
        default_cd_sec=cd_sec,
        plugin_tag=plugin_tag,
    )
    for alias in aliases:
        alias_name = (alias or "").strip()
        if not alias_name or alias_name.casefold() == primary.casefold():
            continue
        alias_matcher = on_command(
            alias_name,
            priority=priority,
            block=block,
            permission=_permission_for_scene(command_id, scene),
        )
        binding.alias_bindings.append(
            PluginCommand(
                matcher=alias_matcher,
                command_id=command_id,
                default_cd_sec=cd_sec,
                plugin_tag=plugin_tag,
            )
        )
    return binding


def group_command(
    command_id: str,
    prefix: str,
    *,
    aliases: Sequence[str] = (),
    cd_sec: int | None = 0,
    priority: int = 5,
    block: bool = True,
) -> PluginCommand:
    return message_command(
        command_id,
        prefix,
        aliases=aliases,
        scene="group",
        cd_sec=cd_sec,
        priority=priority,
        block=block,
    )


def private_command(
    command_id: str,
    prefix: str,
    *,
    aliases: Sequence[str] = (),
    cd_sec: int | None = 0,
    priority: int = 5,
    block: bool = True,
) -> PluginCommand:
    return message_command(
        command_id,
        prefix,
        aliases=aliases,
        scene="private",
        cd_sec=cd_sec,
        priority=priority,
        block=block,
    )


def bind_alias_handlers(primary: PluginCommand, handler: HandlerFunc) -> None:
    """主命令与别名 matcher 绑定同一 handler。"""
    primary.handle(handler)
    for alias_binding in primary.alias_bindings:
        alias_binding.handle(handler)
