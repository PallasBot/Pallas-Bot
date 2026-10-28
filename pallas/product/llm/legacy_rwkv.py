from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .config import LlmConfig


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
    """遗留 RWKV 酒后聊天已退役：不再发起任何 HTTP 请求。"""
    _ = (request_id, session, text, tts, chat_endpoint, timeout_sec, cfg)
    return "", False


async def delete_rwkv_chat_session(
    session_id: str,
    *,
    del_session_endpoint: str = "/api/del_session",
    timeout_sec: float = 30.0,
    cfg: LlmConfig | None = None,
) -> bool:
    """遗留 RWKV 会话删除已退役：不再发起任何 HTTP 请求。"""
    _ = (session_id, del_session_endpoint, timeout_sec, cfg)
    return False
