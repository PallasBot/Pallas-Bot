import time

from nonebot import logger, on_message
from nonebot.adapters import Bot, Event
from nonebot.rule import Rule
from ulid import ULID

from src.features.cmd_perm import group_message_permission_for_command
from src.foundation.config import TaskManager
from src.shared.utils import HTTPXClient

from .config import Config, get_ollama_config, ollama_server_url
from .prompts import get_system_prompt
from .replies import OLLAMA_VAGUE_REPLY

SERVER_URL = ollama_server_url()


def refresh_server_url(cfg: Config | None = None) -> None:
    global SERVER_URL
    SERVER_URL = ollama_server_url(cfg if isinstance(cfg, Config) else get_ollama_config())


def ollama_chat_rule(event: Event) -> bool:
    if not get_ollama_config().ollama_enable:
        return False
    return bool(getattr(event, "to_me", False))


ollama_chat = on_message(
    priority=get_ollama_config().ollama_min_priority + 1,
    block=False,
    rule=Rule(ollama_chat_rule),
    permission=group_message_permission_for_command("ollama.chat"),
)


@ollama_chat.handle()
async def handle_ollama_chat(bot: Bot, event: Event):
    cfg = get_ollama_config()
    if not cfg.ollama_enable:
        return

    plain = event.get_plaintext().strip()
    if plain.casefold() in ("clear", "unload", "model"):
        return

    session_id = event.get_session_id()
    msg = str(event.get_message()).strip()
    if not msg:
        await ollama_chat.send(OLLAMA_VAGUE_REPLY)
        return

    system_prompt = get_system_prompt()
    if not system_prompt:
        logger.error("ollama system prompt file is missing or empty")
        await ollama_chat.send(OLLAMA_VAGUE_REPLY)
        return

    request_id = str(ULID())
    await TaskManager.add_task(
        request_id,
        {
            "bot_id": bot.self_id,
            "group_id": getattr(event, "group_id", None),
            "task_type": "ollama",
            "start_time": time.time(),
        },
    )

    url = f"{SERVER_URL}{cfg.ollama_chat_endpoint}/{request_id}"
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
