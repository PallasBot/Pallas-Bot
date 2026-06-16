import time

from nonebot import logger, on_message
from nonebot.adapters import Bot, Event
from nonebot.rule import Rule
from ulid import ULID

from src.features.cmd_perm import group_message_permission_for_command
from src.foundation.config import TaskManager
from src.shared.utils import HTTPXClient

from .config import Config, get_llm_chat_config, llm_chat_server_url
from .prompts import get_system_prompt
from .replies import LLM_CHAT_VAGUE_REPLY

LLM_CHAT_TASK_TYPE = "llm_chat"

SERVER_URL = llm_chat_server_url()


def refresh_server_url(cfg: Config | None = None) -> None:
    global SERVER_URL
    SERVER_URL = llm_chat_server_url(cfg if isinstance(cfg, Config) else get_llm_chat_config())


def llm_chat_rule(event: Event) -> bool:
    if not get_llm_chat_config().llm_chat_enable:
        return False
    return bool(getattr(event, "to_me", False))


llm_chat_msg = on_message(
    priority=get_llm_chat_config().llm_chat_min_priority + 1,
    block=False,
    rule=Rule(llm_chat_rule),
    permission=group_message_permission_for_command("llm_chat.chat"),
)


@llm_chat_msg.handle()
async def handle_llm_chat(bot: Bot, event: Event):
    cfg = get_llm_chat_config()
    if not cfg.llm_chat_enable:
        return

    plain = event.get_plaintext().strip()
    if plain.casefold() in ("clear", "unload", "model"):
        return

    session_id = event.get_session_id()
    msg = str(event.get_message()).strip()
    if not msg:
        await llm_chat_msg.send(LLM_CHAT_VAGUE_REPLY)
        return

    system_prompt = get_system_prompt()
    if not system_prompt:
        logger.error("llm chat system prompt file is missing or empty")
        await llm_chat_msg.send(LLM_CHAT_VAGUE_REPLY)
        return

    request_id = str(ULID())
    await TaskManager.add_task(
        request_id,
        {
            "bot_id": bot.self_id,
            "group_id": getattr(event, "group_id", None),
            "task_type": LLM_CHAT_TASK_TYPE,
            "start_time": time.time(),
        },
    )

    url = f"{SERVER_URL}{cfg.llm_chat_endpoint}/{request_id}"
    response = await HTTPXClient.post(
        url,
        json={
            "session": session_id,
            "text": msg,
            "system_prompt": system_prompt,
        },
    )
    if not response:
        await TaskManager.remove_task(request_id)
        return

    task_id = response.json().get("task_id", "")
    if not task_id:
        await TaskManager.remove_task(request_id)
