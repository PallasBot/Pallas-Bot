from __future__ import annotations

from nonebot import logger

from pallas.core.shared.utils import HTTPXClient

from .config import LlmConfig, get_llm_config, llm_server_base_url


async def submit_rwkv_drunk_chat(
    *,
    request_id: str,
    session: str,
    text: str,
    tts: bool = False,
    chat_endpoint: str = "/api/chat",
    timeout_sec: float = 30.0,
    cfg: LlmConfig | None = None,
) -> tuple[str, bool]:
    """遗留 RWKV 酒后聊天；返回 (task_id, ok)。"""
    c = cfg or get_llm_config()
    base = llm_server_base_url(c)
    url = f"{base}{chat_endpoint}/{request_id}"
    try:
        response = await HTTPXClient.post(
            url,
            json={
                "session": session,
                "text": text,
                "token_count": 50,
                "tts": tts,
            },
            timeout=timeout_sec,
        )
    except Exception:
        logger.exception("rwkv drunk chat request failed: url={}", url)
        return "", False
    if not response:
        return "", False
    try:
        body = response.json()
    except Exception:
        logger.warning("rwkv drunk chat invalid json: url={}", url)
        return "", False
    task_id = str(body.get("task_id") or "")
    return task_id, bool(task_id)


async def delete_rwkv_chat_session(
    session_id: str,
    *,
    del_session_endpoint: str = "/api/del_session",
    timeout_sec: float = 30.0,
    cfg: LlmConfig | None = None,
) -> bool:
    c = cfg or get_llm_config()
    base = llm_server_base_url(c)
    url = f"{base}{del_session_endpoint}/{session_id}"
    try:
        response = await HTTPXClient.delete(url, timeout=timeout_sec)
    except Exception:
        logger.warning("delete_rwkv_chat_session failed: session={}", session_id)
        return False
    return bool(response) and response.status_code < 400
