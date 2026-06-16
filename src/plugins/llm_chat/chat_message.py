import time

from nonebot import logger, on_message
from nonebot.adapters import Bot, Event
from nonebot.rule import Rule
from ulid import ULID

from src.features.cmd_perm import group_message_permission_for_command
from src.features.llm import ChatSubmitRequest, is_llm_chat_service_enabled, submit_chat_task
from src.features.llm.config import LlmConfig, get_llm_config
from src.features.llm.governance import check_llm_chat_gate, refresh_llm_chat_cooldown
from src.features.llm.session_store import append_llm_message
from src.features.persona.compile_persona_prompt import compile_persona_prompt_for
from src.foundation.config import TaskManager

from .config import Config, get_llm_chat_config
from .prompts import get_system_prompt
from .replies import LLM_CHAT_VAGUE_REPLY

LLM_CHAT_TASK_TYPE = "llm_chat"


def llm_chat_runtime_config(cfg: Config | None = None) -> LlmConfig:
    _ = cfg
    return get_llm_config()


def refresh_server_url(cfg: Config | None = None) -> None:
    _ = cfg


def llm_chat_rule(event: Event) -> bool:
    if not is_llm_chat_service_enabled():
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
    if not is_llm_chat_service_enabled():
        return

    cfg = get_llm_chat_config()
    plain = event.get_plaintext().strip()
    if plain.casefold() in ("clear", "unload", "model"):
        return

    session_id = event.get_session_id()
    msg = str(event.get_message()).strip()
    if not msg:
        await llm_chat_msg.send(LLM_CHAT_VAGUE_REPLY)
        return

    system_prompt = ""
    raw_group_id = getattr(event, "group_id", None)
    group_id = int(raw_group_id) if raw_group_id is not None else None
    user_id = int(getattr(event, "user_id", 0) or 0)
    try:
        bundle = await compile_persona_prompt_for(
            int(bot.self_id),
            group_id,
            base_system_path=cfg.llm_chat_system_prompt_path or None,
        )
        system_prompt = bundle.system.strip()
    except Exception:
        logger.exception("compile_persona_prompt failed, falling back to static system prompt")

    if not system_prompt:
        system_prompt = get_system_prompt()
    if not system_prompt:
        logger.error("llm chat system prompt file is missing or empty")
        await llm_chat_msg.send(LLM_CHAT_VAGUE_REPLY)
        return

    llm_cfg = llm_chat_runtime_config(cfg)
    gate = await check_llm_chat_gate(event, group_id, cfg=llm_cfg)
    if gate is not None:
        logger.debug("llm chat gated: reason={} group={} user={}", gate, group_id, user_id)
        return

    request_id = str(ULID())
    await TaskManager.add_task(
        request_id,
        {
            "bot_id": bot.self_id,
            "group_id": getattr(event, "group_id", None),
            "user_id": user_id,
            "task_type": LLM_CHAT_TASK_TYPE,
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
            user_id=user_id,
        ),
        cfg=llm_cfg,
    )
    if not result.ok:
        await TaskManager.remove_task(request_id)
        return

    await refresh_llm_chat_cooldown(event, default_cd_sec=llm_cfg.llm_chat_cooldown_sec)
    await append_llm_message(int(bot.self_id), group_id, user_id, "user", msg)

    if not result.task_id:
        await TaskManager.remove_task(request_id)
