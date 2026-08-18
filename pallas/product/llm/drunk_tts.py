"""酒后对话附带 TTS：文字发出后另调侧车 /v1/tts（与「牛牛说」同源）。"""

from __future__ import annotations

import time

from nonebot import logger
from ulid import ULID

from pallas.core.foundation.config import BotConfig, TaskManager
from pallas.core.foundation.config.repo_settings import repo_env_raw_value
from pallas.core.platform.ai_callback.task_types import CHAT_DRUNK_TASK_TYPE, TTS_TASK_TYPE
from pallas.core.shared.utils import HTTPXClient

from .config import LlmConfig, get_llm_config, llm_server_base_url, resolve_chat_tts_enabled


def is_chat_tts_enabled(cfg: LlmConfig | None = None) -> bool:
    if cfg is not None:
        return bool(cfg.chat_tts_enable)
    return resolve_chat_tts_enabled()


def drunk_tts_min_drunkenness(cfg: LlmConfig | None = None) -> int:
    c = cfg or get_llm_config()
    return max(0, int(c.drunk_tts_min_drunkenness))


def drunk_tts_min_chars(cfg: LlmConfig | None = None) -> int:
    c = cfg or get_llm_config()
    return max(0, int(c.drunk_tts_min_chars))


def _tts_plugin_enabled() -> bool:
    try:
        from pallas_plugin_tts.config import get_tts_config

        return bool(get_tts_config().tts_enable)
    except Exception:
        return True


def _media_auth_headers() -> dict[str, str]:
    token = ""
    try:
        from pallas_plugin_ai_media_runtime.conn import resolve_media_bearer_token

        token = resolve_media_bearer_token(fallback=(repo_env_raw_value("TTS_API_TOKEN") or "").strip())
    except Exception:
        for key in ("TTS_API_TOKEN", "PALLAS_AI_API_TOKEN", "API_BEARER_TOKEN"):
            token = (repo_env_raw_value(key) or "").strip()
            if token:
                break
    if not token:
        return {}
    return {"Authorization": f"Bearer {token}"}


async def should_attach_drunk_tts(
    *,
    bot_id: int | str,
    group_id: int,
    reply_text: str,
    cfg: LlmConfig | None = None,
) -> bool:
    """酒后回文是否满足「开关 + 醉酒度 + 字数」再附带语音。"""
    c = cfg or get_llm_config()
    if not is_chat_tts_enabled(c):
        return False
    if not _tts_plugin_enabled():
        return False
    reply = (reply_text or "").strip()
    if len(reply) < drunk_tts_min_chars(c):
        return False
    try:
        level = await BotConfig(int(bot_id), int(group_id)).drunkenness()
    except Exception:
        logger.exception("Drunk TTS could not read drunkenness for bot [{}] and group [{}]", bot_id, group_id)
        return False
    return level >= drunk_tts_min_drunkenness(c)


async def enqueue_ai_drunk_tts(
    *,
    bot_id: str | int,
    group_id: int,
    user_id: int | None,
    text: str,
    cfg: LlmConfig | None = None,
    timeout_sec: float | None = None,
) -> bool:
    """文字已发出后，另起侧车 /v1/tts 任务，回调只带语音。"""
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
            "task_type": TTS_TASK_TYPE,
            "start_time": time.time(),
            "voice_only": True,
            "parent_task_type": CHAT_DRUNK_TASK_TYPE,
        },
    )
    base = llm_server_base_url(c).rstrip("/")
    url = f"{base}/v1/tts/{request_id}"
    wait = float(timeout_sec if timeout_sec is not None else max(5.0, c.chat_timeout_sec))
    headers = _media_auth_headers()
    try:
        response = await HTTPXClient.post(
            url,
            json={"text": reply},
            headers=headers or None,
            timeout=wait,
        )
    except Exception:
        logger.exception("Drunk TTS request failed for URL [{}]", url)
        await TaskManager.remove_task(request_id)
        return False
    if not response:
        await TaskManager.remove_task(request_id)
        return False
    try:
        body = response.json()
    except Exception:
        logger.warning("Drunk TTS response contained invalid JSON for URL [{}]", url)
        await TaskManager.remove_task(request_id)
        return False
    if not isinstance(body, dict) or not str(body.get("task_id") or "").strip():
        await TaskManager.remove_task(request_id)
        return False
    logger.info(
        "Drunk TTS enqueued request [{}] for bot [{}] and group [{}] with [{}] characters",
        request_id,
        bot_id,
        group_id,
        len(reply),
    )
    return True
