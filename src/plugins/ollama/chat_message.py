import time

from nonebot import logger, on_message
from nonebot.adapters import Bot, Event
from nonebot.rule import Rule
from ulid import ULID

from src.features.cmd_perm import group_message_permission_for_command
from src.features.llm import ChatSubmitRequest, submit_chat_task
from src.features.llm.config import LlmConfig, get_llm_config
from src.features.persona.compile_persona_prompt import compile_persona_prompt_for
from src.foundation.config import TaskManager

from .config import Config, get_ollama_config
from .prompts import get_system_prompt
from .replies import OLLAMA_VAGUE_REPLY


def ollama_llm_config(cfg: Config) -> LlmConfig:
    base = get_llm_config()
    return base.model_copy(
        update={
            "ai_server_host": cfg.ai_server_host,
            "ai_server_port": cfg.ai_server_port,
            "legacy_chat_endpoint": cfg.ollama_chat_endpoint,
        }
    )


def refresh_server_url(cfg: Config | None = None) -> None:
    """配置热重载钩子；chat 请求经 features/llm 按次读取 server 配置。"""
    _ = cfg


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

    system_prompt = ""
    raw_group_id = getattr(event, "group_id", None)
    group_id = int(raw_group_id) if raw_group_id is not None else None
    try:
        bundle = await compile_persona_prompt_for(
            int(bot.self_id),
            group_id,
            base_system_path=cfg.ollama_system_prompt_path or None,
        )
        system_prompt = bundle.system.strip()
    except Exception:
        logger.exception("compile_persona_prompt failed, falling back to static system prompt")

    if not system_prompt:
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

    result = await submit_chat_task(
        ChatSubmitRequest(
            request_id=request_id,
            session_id=session_id,
            user_text=msg,
            system_prompt=system_prompt,
            bot_id=int(bot.self_id),
            group_id=group_id,
        ),
        cfg=ollama_llm_config(cfg),
    )
    if not result.ok:
        await TaskManager.remove_task(request_id)
        return

    if not result.task_id:
        await TaskManager.remove_task(request_id)
