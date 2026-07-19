"""Bot→AI 统一 capability 请求外壳（与 final §4.2 / AI 仓 media task 信封对齐）。"""

from __future__ import annotations

from typing import Any

from pallas.core.shared.ai_runtime_capability import LLM_CHAT

LLM_CHAT_PLUGIN = "llm_chat"


def build_runtime_caller(*, bot_id: int | None, plugin: str) -> dict[str, Any]:
    return {
        "source": "bot",
        "bot_id": int(bot_id or 0),
        "plugin": str(plugin or LLM_CHAT_PLUGIN).strip() or LLM_CHAT_PLUGIN,
    }


def build_runtime_context(
    *,
    group_id: int | None = None,
    user_id: int | None = None,
    session_id: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    body: dict[str, Any] = {}
    if group_id is not None:
        body["group_id"] = int(group_id)
    if user_id is not None:
        body["user_id"] = int(user_id)
    if session_id:
        body["session_id"] = str(session_id)
    if metadata:
        body["metadata"] = dict(metadata)
    return body


def build_runtime_policy(*, timeout_sec: float | None = None) -> dict[str, Any]:
    policy: dict[str, Any] = {"deliver_mode": "callback"}
    if timeout_sec is not None and timeout_sec > 0:
        policy["timeout_sec"] = float(timeout_sec)
    return policy


def build_llm_chat_capability_body(
    *,
    request_id: str,
    payload: dict[str, Any],
    bot_id: int | None = None,
    group_id: int | None = None,
    user_id: int | None = None,
    session_id: str | None = None,
    timeout_sec: float | None = None,
    plugin: str = LLM_CHAT_PLUGIN,
) -> dict[str, Any]:
    return {
        "request_id": str(request_id),
        "capability": LLM_CHAT.capability_id,
        "caller": build_runtime_caller(bot_id=bot_id, plugin=plugin),
        "context": build_runtime_context(
            group_id=group_id,
            user_id=user_id,
            session_id=session_id,
        ),
        "policy": build_runtime_policy(timeout_sec=timeout_sec),
        "payload": payload,
    }
