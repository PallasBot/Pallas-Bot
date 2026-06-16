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
from src.features.llm import ChatSubmitRequest, delete_llm_chat_session, get_llm_config, submit_chat_task
from src.features.persona.compile_persona_prompt import compile_persona_prompt_for
from src.foundation.config import BotConfig, GroupConfig, TaskManager

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
                "detail_des": "须先「牛牛喝酒」；与随时闲聊共用 AI 网关与牛格 prompt。",
            },
        ],
    },
)


def refresh_server_url(cfg: Config | None = None) -> None:
    _ = cfg or get_chat_config()


refresh_server_url()
CHAT_COOLDOWN_KEY = "chat"

if plugin_config.chat_enable:

    @BotConfig.handle_sober_up
    async def on_sober_up(bot_id, group_id, drunkenness) -> None:
        session = f"{bot_id}_{group_id}"
        logger.info(f"bot [{bot_id}] sober up in group [{group_id}], clear session [{session}]")
        await delete_llm_chat_session(session, cfg=get_llm_config())


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

    group_id = int(event.group_id)
    user_id = int(event.user_id)
    session = f"{event.self_id}_{group_id}"
    try:
        bundle = await compile_persona_prompt_for(int(bot.self_id), group_id, mode="drunk")
        system_prompt = bundle.system.strip()
    except Exception:
        logger.exception("compile_persona_prompt drunk mode failed")
        return
    if not system_prompt:
        return

    request_id = str(ULID())
    await TaskManager.add_task(
        request_id,
        {
            "bot_id": bot.self_id,
            "group_id": group_id,
            "user_id": user_id,
            "task_type": "chat",
            "start_time": time.time(),
        },
    )

    result = await submit_chat_task(
        ChatSubmitRequest(
            request_id=request_id,
            session_id=session,
            user_text=text,
            system_prompt=system_prompt,
            bot_id=int(bot.self_id),
            group_id=group_id,
            user_id=user_id,
            mode="drunk",
            token_count=50,
        ),
        cfg=get_llm_config(),
    )
    if not result.ok:
        await TaskManager.remove_task(request_id)
