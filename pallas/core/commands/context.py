"""插件 handler 统一上下文。"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from nonebot.adapters.onebot.v11 import GroupMessageEvent, MessageEvent, PrivateMessageEvent

if TYPE_CHECKING:
    from nonebot.adapters import Bot
    from nonebot.matcher import Matcher


class PluginHandlerContext:
    def __init__(
        self,
        *,
        bot: Bot,
        event: MessageEvent,
        command_id: str,
        matcher: Matcher,
        plugin_tag: str = "",
    ) -> None:
        self.bot = bot
        self.event = event
        self.command_id = command_id
        self.matcher = matcher
        self.plugin_tag = (plugin_tag or command_id.split(".", 1)[0]).strip()

    @property
    def is_group(self) -> bool:
        return isinstance(self.event, GroupMessageEvent)

    @property
    def is_private(self) -> bool:
        return isinstance(self.event, PrivateMessageEvent)

    @property
    def group_id(self) -> int | None:
        if isinstance(self.event, GroupMessageEvent):
            return int(self.event.group_id)
        return None

    @property
    def user_id(self) -> str:
        return str(self.event.get_user_id())

    @property
    def plain_text(self) -> str:
        return str(getattr(self.event, "get_plaintext", lambda: "")() or "")

    async def finish(self, message: Any = None, **kwargs: Any) -> None:
        await self.matcher.finish(message, **kwargs)
