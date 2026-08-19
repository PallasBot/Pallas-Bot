"""群聊历史工具：按需读取完整群消息，供模型回答「最近聊了什么」。"""

from __future__ import annotations

import hashlib
import time
from typing import TYPE_CHECKING, Any

from pallas.product.llm.inference_params import task_token_budget
from pallas.product.llm.tools.contracts import ToolCapability
from pallas.product.llm.tools.registry import LlmToolSpec, register_tool
from pallas.product.persona.prompt_guard import sanitize_prompt_literal

if TYPE_CHECKING:
    from pallas.product.llm.tools.context import ToolInvokeContext


_RECENT_SUMMARY_CACHE_TTL_SEC = 600.0
_recent_summary_cache: dict[tuple[int, int], tuple[float, str, str]] = {}
_RECENT_SUMMARY_SYSTEM = """总结当前群最近聊天。只写主要话题、已经达成的结论和明显分歧；
忽略寒暄、刷屏、命令、辱骂和敏感隐私。若消息不足以形成话题，只说“最近没有形成明确话题”。
只输出不超过120字的中文总结，不要标题、列表或解释。"""


def register_history_tools() -> None:
    register_tool(
        LlmToolSpec(
            name="chat.history",
            description="读取当前群最近的完整聊天记录。用户问「最近聊了什么」「刚才发生什么」「总结群聊」时使用。",
            parameters={"type": "object", "properties": {"limit": {"type": "integer"}}, "required": []},
            domains=frozenset({"chat", "history"}),
            handler=handle_chat_history,
            capabilities=frozenset({ToolCapability.READ_ONLY.value, ToolCapability.REQUIRES_GROUP_CONTEXT.value}),
            visibility="deferred",
            hints=frozenset({"聊天记录", "看聊天记录", "翻聊天记录", "翻历史"}),
        )
    )
    register_tool(
        LlmToolSpec(
            name="chat.recent_summary",
            description="总结当前群最近的聊天内容。用户问“最近聊了什么”“刚才发生什么”“总结群聊”时使用。",
            parameters={"type": "object", "properties": {}, "required": []},
            domains=frozenset({"chat", "history"}),
            handler=handle_recent_summary,
            capabilities=frozenset({ToolCapability.READ_ONLY.value, ToolCapability.REQUIRES_GROUP_CONTEXT.value}),
            visibility="deferred",
            hints=frozenset({
                "最近聊了什么",
                "最近在聊什么",
                "刚才聊了什么",
                "刚才在聊什么",
                "总结一下群聊",
                "群里最近",
            }),
            estimated_duration_ms=1500,
        )
    )


async def handle_chat_history(arguments: dict[str, Any], context: ToolInvokeContext | None = None) -> dict[str, Any]:
    if context is None or context.group_id is None:
        return {"ok": False, "error": "group_context_required"}
    limit = max(6, min(int((arguments or {}).get("limit") or 24), 32))
    rows = await recent_group_message_rows(context, limit=limit)
    return {
        "ok": True,
        "result": {
            "message_count": len(rows),
            "messages": rows,
            "hint": "请只总结主要话题、已达成结论和明显分歧；不要复述全部流水账或泄露敏感信息。",
        },
    }


async def recent_group_message_rows(context: ToolInvokeContext, *, limit: int) -> list[dict[str, Any]]:
    from pallas.core.foundation.db import make_message_repository

    messages = await make_message_repository().find_recent_in_group(int(context.group_id or 0), limit=limit + 1)
    rows: list[dict[str, Any]] = []
    total_chars = 0
    for message in messages[-limit:]:
        if int(getattr(message, "user_id", 0) or 0) == int(context.bot_id):
            continue
        text = sanitize_prompt_literal(str(getattr(message, "plain_text", "") or ""), max_len=180)
        if not text:
            continue
        if total_chars + len(text) > 3600:
            break
        total_chars += len(text)
        speaker = sanitize_prompt_literal(str(getattr(message, "sender_name", "") or ""), max_len=40)
        rows.append({
            "speaker": speaker or f"群友#{int(getattr(message, 'user_id', 0) or 0) % 10000:04d}",
            "text": text,
            "time": int(getattr(message, "time", 0) or 0),
        })
    return rows


async def handle_recent_summary(arguments: dict[str, Any], context: ToolInvokeContext | None = None) -> dict[str, Any]:
    del arguments
    if context is None or context.group_id is None:
        return {"ok": False, "error": "group_context_required"}
    rows = await recent_group_message_rows(context, limit=24)
    if len(rows) < 6:
        return {
            "ok": True,
            "result": {"summary": "最近消息不多，还没有形成明确话题。", "message_count": len(rows)},
        }
    transcript = "\n".join(f"{item['speaker']}：{item['text']}" for item in rows)
    signature = hashlib.blake2b(transcript.encode("utf-8"), digest_size=12).hexdigest()
    cache_key = (int(context.bot_id), int(context.group_id))
    cached = _recent_summary_cache.get(cache_key)
    now = time.monotonic()
    if cached is not None and cached[0] > now and cached[1] == signature:
        summary = cached[2]
    else:
        from pallas.product.llm.config import get_llm_config
        from pallas.product.llm.provider_client import complete_chat_message

        cfg = get_llm_config()
        response = await complete_chat_message(
            [{"role": "system", "content": _RECENT_SUMMARY_SYSTEM}, {"role": "user", "content": transcript}],
            model="",
            options={"temperature": 0.2, "max_tokens": task_token_budget("memory_extract")},
            task="memory_extract",
            cfg=cfg,
        )
        summary = sanitize_prompt_literal(str(response.get("content") or ""), max_len=240)
        if not summary:
            summary = "最近消息较多，但暂时无法整理出明确话题。"
        _recent_summary_cache[cache_key] = (now + _RECENT_SUMMARY_CACHE_TTL_SEC, signature, summary)
    return {
        "ok": True,
        "result": {"summary": summary, "message_count": len(rows)},
        "summary": summary,
    }
