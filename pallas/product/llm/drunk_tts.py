"""酒后对话 TTS：经 AI Runtime /tts（与旧扩展 chat 同源）。"""

from __future__ import annotations

import time

from nonebot import logger
from ulid import ULID

from pallas.core.foundation.config import TaskManager
from pallas.core.platform.ai_callback.task_types import CHAT_DRUNK_TASK_TYPE
from pallas.core.shared.utils import HTTPXClient

from .config import LlmConfig, get_llm_config, llm_server_base_url, resolve_chat_tts_enabled


def is_chat_tts_enabled(cfg: LlmConfig | None = None) -> bool:
    if cfg is not None:
        return bool(cfg.chat_tts_enable)
    return resolve_chat_tts_enabled()


async def enqueue_ai_drunk_tts(
    *,
    bot_id: str | int,
    group_id: int,
    user_id: int | None,
    text: str,
    cfg: LlmConfig | None = None,
    timeout_sec: float | None = None,
) -> bool:
    """文字已发出后，另起 AI /tts 任务，回调只带语音。"""
    reply = (text or "").strip()
    if not reply:
        return False
    c = cfg or get_llm_config()
    request_id = str(ULID())
    await TaskManager.add_task(
        request_id,
        {
            "bot_id": str(bot_id),
            "group_id": int(group_id),
            "user_id": int(user_id) if user_id is not None else None,
            "task_type": CHAT_DRUNK_TASK_TYPE,
            "start_time": time.time(),
            "voice_only": True,
        },
    )
    base = llm_server_base_url(c)
    url = f"{base}/tts/{request_id}"
    wait = float(timeout_sec if timeout_sec is not None else c.chat_timeout_sec)
    try:
        response = await HTTPXClient.post(url, json={"text": reply}, timeout=wait)
    except Exception:
        logger.exception("drunk tts request failed: url={}", url)
        await TaskManager.remove_task(request_id)
        return False
    if not response:
        await TaskManager.remove_task(request_id)
        return False
    try:
        body = response.json()
    except Exception:
        logger.warning("drunk tts invalid json: url={}", url)
        await TaskManager.remove_task(request_id)
        return False
    if not str(body.get("task_id") or "").strip():
        await TaskManager.remove_task(request_id)
        return False
    return True
