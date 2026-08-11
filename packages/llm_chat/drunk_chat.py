"""酒后对话：醉酒时 @ / 「牛牛 + 文本」走 drunk 提交路径。"""

from __future__ import annotations

import time

from nonebot import logger, on_message
from nonebot.adapters import Bot  # noqa: TC002  # NoneBot 依赖解析需要运行时可见
from nonebot.adapters.onebot.v11 import GroupMessageEvent, permission
from nonebot.rule import Rule
from ulid import ULID

from pallas.api.logging import format_plugin_event
from pallas.core.foundation.config import BotConfig, GroupConfig, TaskManager
from pallas.core.platform.ai_callback.task_types import CHAT_DRUNK_TASK_TYPE
from pallas.product.llm import (
    ChatSubmitRequest,
    build_drunk_chat_system_prompt,
    delete_llm_chat_session,
    is_legacy_rwkv_drunk_chat_enabled,
    is_llm_chat_service_enabled,
    submit_chat_task,
)
from pallas.product.llm.drunk_tts import is_chat_tts_enabled
from pallas.product.llm.legacy_rwkv import delete_rwkv_chat_session, submit_rwkv_drunk_chat
from pallas.product.llm.session_store import clear_llm_messages

CHAT_COOLDOWN_KEY = "chat"
# 与历史扩展仓 chat 一致：优先于清醒 @（llm_chat 默认 ~51）
DRUNK_CHAT_PRIORITY = 13


def extension_drunk_chat_loaded() -> bool:
    """旧版 ai-media `pallas_plugin_chat` 仍加载时，由扩展仓接管酒后对话。"""
    try:
        from nonebot import get_loaded_plugins
    except Exception:
        return False
    for plugin in get_loaded_plugins():
        name = str(getattr(plugin, "name", "") or "").strip()
        if name in {"chat", "pallas_plugin_chat"}:
            return True
        module = getattr(plugin, "module", None)
        mod_name = str(getattr(module, "__name__", "") or "")
        if mod_name == "pallas_plugin_chat" or mod_name.startswith("pallas_plugin_chat."):
            return True
    return False


@BotConfig.handle_sober_up
async def on_sober_up(bot_id, group_id, drunkenness) -> None:
    if extension_drunk_chat_loaded():
        return
    session = f"{bot_id}_{group_id}"
    logger.info(
        format_plugin_event(
            "clear_session",
            f"Bot [{bot_id}] cleared drunk-chat session [{session}] in group [{group_id}]",
        )
    )
    try:
        await clear_llm_messages(int(bot_id), int(group_id))
    except Exception:
        logger.exception(
            format_plugin_event(
                "clear_session",
                f"Bot [{bot_id}] failed to clear drunk-chat session [{session}] in group [{group_id}]",
            )
        )
    await delete_llm_chat_session(session)
    if is_legacy_rwkv_drunk_chat_enabled():
        await delete_rwkv_chat_session(session)


async def is_to_drunk_chat(event: GroupMessageEvent) -> bool:
    if extension_drunk_chat_loaded():
        return False
    if not (is_llm_chat_service_enabled() or is_legacy_rwkv_drunk_chat_enabled()):
        return False
    text = event.get_plaintext()
    if not text.startswith("牛牛") and not event.is_tome():
        return False
    config = BotConfig(event.self_id, event.group_id)
    return (await config.drunkenness()) > 0


drunk_msg = on_message(
    rule=Rule(is_to_drunk_chat),
    priority=DRUNK_CHAT_PRIORITY,
    block=True,
    permission=permission.GROUP,
)


@drunk_msg.handle()
async def handle_drunk_chat(bot: Bot, event: GroupMessageEvent):
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

    session = f"{bot.self_id}_{event.group_id}"
    request_id = str(ULID())
    want_tts = is_chat_tts_enabled()
    await TaskManager.add_task(
        request_id,
        {
            "bot_id": bot.self_id,
            "group_id": event.group_id,
            "user_id": event.user_id,
            "task_type": CHAT_DRUNK_TASK_TYPE,
            "start_time": time.time(),
            "want_tts": want_tts,
        },
    )

    if is_llm_chat_service_enabled():
        prompt_ctx = await build_drunk_chat_system_prompt(
            int(bot.self_id),
            int(event.group_id),
            text,
            user_id=int(event.user_id),
        )
        if prompt_ctx is None:
            await TaskManager.remove_task(request_id)
            logger.warning(
                "drunk chat system prompt empty: bot={} group={}",
                bot.self_id,
                event.group_id,
            )
            return
        result = await submit_chat_task(
            ChatSubmitRequest(
                request_id=request_id,
                session_id=session,
                user_text=text,
                system_prompt=prompt_ctx.system_prompt,
                bot_id=int(bot.self_id),
                group_id=int(event.group_id),
                user_id=int(event.user_id),
                mode="drunk",
                task="drunk",
                token_count=prompt_ctx.token_count or 50,
                temperature=prompt_ctx.temperature,
            )
        )
    elif is_legacy_rwkv_drunk_chat_enabled():
        task_id, ok = await submit_rwkv_drunk_chat(
            request_id=request_id,
            session=session,
            text=text,
            tts=want_tts,
        )
        result = type("LegacyResult", (), {"ok": ok, "task_id": task_id})()
    else:
        await TaskManager.remove_task(request_id)
        return

    if not result or not getattr(result, "ok", False):
        await TaskManager.remove_task(request_id)
        return
    task_id = str(getattr(result, "task_id", "") or "")
    if not task_id:
        await TaskManager.remove_task(request_id)
        return
    logger.info(
        format_plugin_event(
            "queue_generate",
            f"Bot [{bot.self_id}] queued a drunk reply for user [{event.user_id}] "
            f"in group [{event.group_id}] as task [{task_id}]",
        )
    )
