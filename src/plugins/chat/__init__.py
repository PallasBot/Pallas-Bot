import time

from nonebot import logger, on_message
from nonebot.adapters import Bot
from nonebot.adapters.onebot.v11 import GroupMessageEvent, permission
from nonebot.plugin import PluginMetadata
from nonebot.rule import Rule
from ulid import ULID

from src.features.cmd_perm.metadata_defaults import (
    PLUGIN_EXTRA_VERSION,
    PLUGIN_HOMEPAGE,
    PLUGIN_MENU_TEMPLATE,
)
from src.features.cmd_perm.metadata_text import SCENE_GROUP, join_usage, usage_line
from src.foundation.config import BotConfig, GroupConfig, TaskManager
from src.shared.utils import HTTPXClient

from .config import Config, get_chat_config, plugin_config

__plugin_meta__ = PluginMetadata(
    name="酒后聊天",
    description="牛牛醉酒时在群内进行 AI 对话。",
    usage=join_usage(
        usage_line("@牛牛", "醉酒时与牛牛对话"),
        usage_line("牛牛 + 文本", "以「牛牛」开头的消息"),
    ),
    type="application",
    homepage=PLUGIN_HOMEPAGE,
    supported_adapters={"~onebot.v11"},
    extra={
        "version": PLUGIN_EXTRA_VERSION,
        "menu_template": PLUGIN_MENU_TEMPLATE,
        "ingress_route": {"lane": "remote"},
        "menu_data": [
            {
                "func": "酒后聊天",
                "trigger_method": "on_message",
                "trigger_scene": SCENE_GROUP,
                "trigger_condition": "@牛牛 / 牛牛 + 文本",
                "brief_des": "醉酒时 AI 对话",
                "detail_des": "须先「牛牛喝酒」；牛牛根据上下文回复，启用 TTS 时可能附带语音。",
            },
        ],
    },
)


def refresh_server_url(cfg: Config | None = None) -> None:
    global SERVER_URL
    c = cfg or get_chat_config()
    SERVER_URL = f"http://{c.ai_server_host}:{c.ai_server_port}"


refresh_server_url()
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
