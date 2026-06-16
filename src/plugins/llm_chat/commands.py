from nonebot import on_command
from nonebot.adapters import Bot, Event
from nonebot.rule import to_me

from src.features.cmd_perm import group_message_permission_for_command
from src.features.llm import delete_llm_chat_session, get_llm_config, is_llm_chat_service_enabled
from src.features.llm.session_store import clear_llm_messages, clear_user_llm_messages
from src.shared.utils import HTTPXClient

from .config import get_llm_chat_config, llm_chat_server_url
from .replies import LLM_CHAT_CLEAR_OK

llm_clear_cmd = on_command(
    cmd="clear",
    priority=get_llm_chat_config().llm_chat_min_priority,
    block=True,
    rule=to_me(),
    permission=group_message_permission_for_command("llm_chat.clear"),
)


@llm_clear_cmd.handle()
async def handle_llm_clear(bot: Bot, event: Event):
    if not is_llm_chat_service_enabled():
        return

    cfg = get_llm_chat_config()
    session_id = event.get_session_id()
    llm_cfg = get_llm_config()
    if llm_cfg.use_unified_chat_api:
        await delete_llm_chat_session(session_id, cfg=llm_cfg)
    else:
        url = f"{llm_chat_server_url()}{cfg.llm_del_session_endpoint}/{session_id}"
        await HTTPXClient.delete(url)
    raw_group_id = getattr(event, "group_id", None)
    group_id = int(raw_group_id) if raw_group_id is not None else None
    user_id = int(getattr(event, "user_id", 0) or 0)
    if user_id:
        await clear_user_llm_messages(int(bot.self_id), group_id, user_id)
    else:
        await clear_llm_messages(int(bot.self_id), group_id)
    await llm_clear_cmd.send(LLM_CHAT_CLEAR_OK)
