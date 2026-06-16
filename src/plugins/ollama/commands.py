from nonebot import logger, on_command
from nonebot.adapters import Bot, Event
from nonebot.adapters.onebot.v11 import Message
from nonebot.params import CommandArg
from nonebot.rule import to_me

from src.features.cmd_perm import (
    group_message_permission_for_command,
    group_or_private_message_permission_for_command,
)
from src.features.llm import delete_llm_chat_session, get_llm_config
from src.features.llm.session_store import clear_llm_messages, clear_user_llm_messages
from src.shared.utils import HTTPXClient
from src.shared.utils.http_msg import user_failure_reply

from .config import get_ollama_config, ollama_server_url
from .replies import OLLAMA_CLEAR_OK, OLLAMA_MODEL_CURRENT, OLLAMA_MODEL_OK, OLLAMA_UNLOAD_OK

ollama_unload_cmd = on_command(
    cmd="unload",
    priority=get_ollama_config().ollama_min_priority,
    block=True,
    rule=to_me(),
    permission=group_message_permission_for_command("ollama.unload"),
)


@ollama_unload_cmd.handle()
async def handle_ollama_unload(bot: Bot, event: Event):
    cfg = get_ollama_config()
    if not cfg.ollama_enable:
        return

    url = f"{ollama_server_url()}{cfg.ollama_unload_endpoint}"
    logger.info("ollama unload request sending: url={}", url)
    response = await HTTPXClient.post(url, json={})
    if response and response.status_code == 200:
        await ollama_unload_cmd.send(OLLAMA_UNLOAD_OK)
        return
    body = response.text if response else ""
    await ollama_unload_cmd.send(user_failure_reply(body))


ollama_clear_cmd = on_command(
    cmd="clear",
    priority=get_ollama_config().ollama_min_priority,
    block=True,
    rule=to_me(),
    permission=group_message_permission_for_command("ollama.clear"),
)


@ollama_clear_cmd.handle()
async def handle_ollama_clear(bot: Bot, event: Event):
    cfg = get_ollama_config()
    if not cfg.ollama_enable:
        return

    session_id = event.get_session_id()
    llm_cfg = get_llm_config()
    if llm_cfg.use_unified_chat_api:
        await delete_llm_chat_session(session_id, cfg=llm_cfg)
    else:
        url = f"{ollama_server_url()}{cfg.ollama_del_session_endpoint}/{session_id}"
        await HTTPXClient.delete(url)
    raw_group_id = getattr(event, "group_id", None)
    group_id = int(raw_group_id) if raw_group_id is not None else None
    user_id = int(getattr(event, "user_id", 0) or 0)
    if user_id:
        await clear_user_llm_messages(int(bot.self_id), group_id, user_id)
    else:
        await clear_llm_messages(int(bot.self_id), group_id)
    await ollama_clear_cmd.send(OLLAMA_CLEAR_OK)


ollama_model_cmd = on_command(
    cmd="model",
    priority=get_ollama_config().ollama_min_priority,
    block=True,
    rule=to_me(),
    permission=group_or_private_message_permission_for_command("ollama.set_model"),
)


@ollama_model_cmd.handle()
async def handle_ollama_model(bot: Bot, event: Event, args: Message = CommandArg()):  # noqa: B008
    cfg = get_ollama_config()
    if not cfg.ollama_enable:
        return

    model_name = args.extract_plain_text().strip()
    url = f"{ollama_server_url()}{cfg.ollama_model_endpoint}"

    if not model_name:
        response = await HTTPXClient.get(url)
        if response and response.status_code == 200:
            model = response.json().get("model", "").strip()
            if model:
                await ollama_model_cmd.send(OLLAMA_MODEL_CURRENT.format(model))
                return
        body = response.text if response else ""
        await ollama_model_cmd.send(user_failure_reply(body))
        return

    logger.info("ollama model switch request: model={}", model_name)
    response = await HTTPXClient.put(url, json={"model": model_name, "pull": True})
    if response and response.status_code == 200:
        model = response.json().get("model", model_name).strip() or model_name
        await ollama_model_cmd.send(OLLAMA_MODEL_OK.format(model))
        return
    body = response.text if response else ""
    await ollama_model_cmd.send(user_failure_reply(body))
