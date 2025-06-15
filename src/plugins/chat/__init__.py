import asyncio

from nonebot import get_plugin_config, logger, on_message
from nonebot.adapters import Bot, Event
from nonebot.adapters.onebot.v11 import GroupMessageEvent, MessageSegment, permission
from nonebot.rule import Rule

from src.common.config import BotConfig, GroupConfig
from src.common.utils import HTTPXClient

from .config import Config

plugin_config = get_plugin_config(Config)

SERVER_URL = f"http://{plugin_config.ai_server_host}:{plugin_config.ai_server_port}"


@BotConfig.handle_sober_up
async def on_sober_up(bot_id, group_id, drunkenness) -> None:
    session = f"{bot_id}_{group_id}"
    logger.info(f"bot [{bot_id}] sober up in group [{group_id}], clear session [{session}]")
    url = f"{SERVER_URL}{plugin_config.del_session_endpoint}/{session}"
    await HTTPXClient.delete(url)


def is_drunk(event: GroupMessageEvent) -> int:
    config = BotConfig(event.self_id, event.group_id)
    return config.drunkenness()


drunk_msg = on_message(
    rule=Rule(is_drunk),
    priority=13,
    block=True,
    permission=permission.GROUP,
)


@drunk_msg.handle()
async def _(event: GroupMessageEvent):
    text = event.get_plaintext()
    if not text.startswith("牛牛") and not event.is_tome():
        return

    config = GroupConfig(event.group_id, cooldown=10)
    cd_key = "chat"
    if not await config.is_cooldown(cd_key):
        return
    await config.refresh_cooldown(cd_key)

    session = f"{event.self_id}_{event.group_id}"
    if text.startswith("牛牛"):
        text = text[2:].strip()
    if "\n" in text:
        text = text.split("\n")[0]
    if len(text) > 50:
        text = text[:50]
    if not text:
        return
    url = f"{SERVER_URL}{plugin_config.chat_endpoint}"
    # response = await HTTPXClient.post(
    #     url, json={"session": session, "text": text, "token_count": 50, "tts": plugin_config.tts_enable}
    # )
    # if response:
    #     task_id = response.json().get("task_id", "")
    # else:
    #     return
