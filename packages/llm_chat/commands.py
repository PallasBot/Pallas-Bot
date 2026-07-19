from pallas.core.commands import PluginHandlerContext, bind_alias_handlers, group_command
from pallas.product.llm import delete_llm_chat_session, get_llm_config, is_llm_chat_service_enabled
from pallas.product.llm.session_store import clear_llm_messages, clear_user_llm_messages

from .config import get_llm_chat_config
from .replies import LLM_CHAT_CLEAR_OK


def clear_invocation_allowed(event: object) -> bool:
    if getattr(event, "to_me", False):
        return True
    sender = getattr(event, "sender", None)
    nickname = ""
    if isinstance(sender, dict):
        nickname = str(sender.get("nickname") or "")
    else:
        nickname = str(getattr(sender, "nickname", "") or "")
    return nickname == "llm"


clear_cmd = group_command(
    "llm_chat.clear",
    "clear",
    priority=get_llm_chat_config().llm_chat_min_priority,
    block=True,
)


async def handle_llm_clear(ctx: PluginHandlerContext) -> None:
    if not clear_invocation_allowed(ctx.event):
        return
    if not is_llm_chat_service_enabled():
        return

    session_id = ctx.event.get_session_id()
    llm_cfg = get_llm_config()
    await delete_llm_chat_session(session_id, cfg=llm_cfg)
    user_id = int(getattr(ctx.event, "user_id", 0) or 0)
    bot_id = int(ctx.bot.self_id)
    if user_id:
        await clear_user_llm_messages(bot_id, ctx.group_id, user_id)
    else:
        await clear_llm_messages(bot_id, ctx.group_id)
    await ctx.matcher.send(LLM_CHAT_CLEAR_OK)


bind_alias_handlers(clear_cmd, handle_llm_clear)
