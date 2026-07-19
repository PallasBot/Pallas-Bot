"""将 LLM tool 参数渲染为插件口令并派发到群消息处理链。"""

from __future__ import annotations

import time
from string import Formatter
from typing import TYPE_CHECKING, Any

import nonebot.message as nb_message
from nonebot import get_bot, logger
from nonebot.adapters.onebot.v11 import GroupMessageEvent, Message

from pallas.core.perm import satisfies_command_permission

if TYPE_CHECKING:
    from pallas.product.llm.tools.context import ToolInvokeContext


class CommandTemplateError(ValueError):
    pass


def render_command_template(template: str, arguments: dict[str, Any]) -> str:
    """用 tool 参数填充口令模板，缺失键抛错。"""
    fields = {field_name for _, field_name, _, _ in Formatter().parse(template) if field_name}
    missing = [name for name in fields if name not in arguments]
    if missing:
        msg = f"missing template fields: {', '.join(missing)}"
        raise CommandTemplateError(msg)
    try:
        return template.format(**{key: str(arguments[key]) for key in fields})
    except (KeyError, ValueError) as exc:
        raise CommandTemplateError(str(exc)) from exc


def build_synthetic_group_event(
    *,
    bot_id: int,
    group_id: int,
    user_id: int,
    text: str,
) -> GroupMessageEvent:
    plain = (text or "").strip()
    return GroupMessageEvent(
        time=int(time.time()),
        self_id=bot_id,
        post_type="message",
        message_type="group",
        sub_type="normal",
        message_id=-int(time.time() * 1000) % 2_000_000_000,
        user_id=user_id,
        message=Message(plain),
        raw_message=plain,
        font=0,
        sender={"user_id": user_id, "nickname": "llm", "card": "", "role": "member"},
        group_id=group_id,
    )


async def dispatch_group_command_text(
    ctx: ToolInvokeContext,
    *,
    command_id: str,
    command_text: str,
) -> dict[str, Any]:
    if ctx.group_id is None:
        return {"ok": False, "error": "group_context_required"}
    plain = (command_text or "").strip()
    if not plain:
        return {"ok": False, "error": "empty_command_text"}

    try:
        bot = get_bot(str(ctx.bot_id))
    except Exception as err:
        logger.warning(f"llm command dispatch get_bot failed bot_id={ctx.bot_id}: {err}")
        return {"ok": False, "error": "bot_unavailable"}

    event = build_synthetic_group_event(
        bot_id=ctx.bot_id,
        group_id=ctx.group_id,
        user_id=ctx.user_id,
        text=plain,
    )
    if not await satisfies_command_permission(bot, event, command_id):
        return {"ok": False, "error": "permission_denied", "command_id": command_id}

    await nb_message.handle_event(bot, event)
    return {
        "ok": True,
        "dispatched": True,
        "command_id": command_id,
        "command_text": plain,
    }
