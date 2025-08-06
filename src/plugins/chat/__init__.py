import time

from nonebot import get_plugin_config, logger, on_message
from nonebot.adapters import Bot
from nonebot.adapters.onebot.v11 import GroupMessageEvent, permission
from nonebot.plugin import PluginMetadata
from nonebot.rule import Rule
from ulid import ULID

from src.common.config import BotConfig, GroupConfig, TaskManager
from src.common.utils import HTTPXClient

from .config import Config

__plugin_meta__ = PluginMetadata(
    name="酒后聊天",
    description="牛牛喝酒后开启的智能聊天功能",
    usage="""
在牛牛喝酒后，可以通过以下方式与牛牛聊天：
1. @牛牛进行聊天
2. 消息以"牛牛"开头与牛牛对话

注意：该功能需要牛牛处于醉酒状态才能使用
    """.strip(),
    type="application",
    homepage="https://github.com/PallasBot",
    supported_adapters=["~onebot.v11"],
    extra={
        "version": "2.0.0",
        "menu_data": [
            {
                "func": "酒后智能聊天",
                "trigger_method": "on_message",
                "trigger_condition": "@牛牛 或 消息以'牛牛'开头",
                "brief_des": "在牛牛醉酒时转为ChatRWKV模型AI聊天",
                "detail_des": "当牛牛处于醉酒状态时，用户可以通过@牛牛或以'牛牛'开头的消息与其进行智能对话。牛牛会根据上下文进行回复，并可能附带语音回复（如果启用了TTS功能）。",  # noqa: E501
            },
        ],
        "menu_template": "default",
    },
)


plugin_config = get_plugin_config(Config)

SERVER_URL = f"http://{plugin_config.ai_server_host}:{plugin_config.ai_server_port}"
CHAT_COOLDOWN_KEY = "chat"

if plugin_config.chat_enable:

    @BotConfig.handle_sober_up
    async def on_sober_up(bot_id, group_id, drunkenness) -> None:
        session = f"{bot_id}_{group_id}"
        logger.info(f"bot [{bot_id}] sober up in group [{group_id}], clear session [{session}]")
        url = f"{SERVER_URL}{plugin_config.del_session_endpoint}/{session}"
        await HTTPXClient.delete(url)


async def is_to_chat(event: GroupMessageEvent) -> bool:
    if plugin_config.chat_enable is False:
        return False
    text = event.get_plaintext()
    if not text.startswith("牛牛") and not event.is_tome():
        return False
    config = BotConfig(event.self_id, event.group_id)
    drunkness = await config.drunkenness()
    return drunkness > 0


drunk_msg = on_message(
    rule=Rule(is_to_chat),
    priority=13,
    block=True,
    permission=permission.GROUP,
)


@drunk_msg.handle()
async def _(bot: Bot, event: GroupMessageEvent):
    config = GroupConfig(event.group_id, cooldown=10)
    if not await config.is_cooldown(CHAT_COOLDOWN_KEY):
        return
    await config.refresh_cooldown(CHAT_COOLDOWN_KEY)

    text = event.get_plaintext()
    if text.startswith("牛牛"):
        text = text[2:].strip()
    if "\n" in text:
        text = text.split("\n")[0]
    text = text[:50].strip()
    if not text:
        return

    session = f"{event.self_id}_{event.group_id}"
    request_id = str(ULID())
    await TaskManager.add_task(
        request_id,
        {
            "bot_id": bot.self_id,
            "group_id": event.group_id,
            "task_type": "chat",
            "start_time": time.time(),
        },
    )

    url = f"{SERVER_URL}{plugin_config.chat_endpoint}/{request_id}"
    response = await HTTPXClient.post(
        url,
        json={
            "session": session,
            "text": text,
            "token_count": 50,
            "tts": plugin_config.tts_enable,
        },
    )
    if not response:
        await TaskManager.remove_task(request_id)
        return

    task_id = response.json().get("task_id", "")
    if not task_id:
        await TaskManager.remove_task(request_id)
        return
