"""群记忆 builtin LLM tools：search / save。"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from pallas.product.llm.config import get_llm_config
from pallas.product.llm.kernel.memory_governance import can_read_persistent_memory
from pallas.product.llm.memory.store import (
    is_llm_memory_store_available,
    retrieve_memory_hits,
    save_memory_entry,
)
from pallas.product.llm.tools.contracts import ToolCapability
from pallas.product.llm.tools.registry import LlmToolSpec, register_tool

_READ_ONLY = frozenset({ToolCapability.READ_ONLY.value})
_SIDE_EFFECT = frozenset({ToolCapability.SIDE_EFFECTING.value, ToolCapability.REQUIRES_GROUP_CONTEXT.value})

if TYPE_CHECKING:
    from pallas.product.llm.tools.context import ToolInvokeContext


def register_memory_tools() -> None:
    register_tool(
        LlmToolSpec(
            name="memory.search",
            description="按关键词检索当前群已记住的群内旧事（teach / auto_episode）。",
            parameters={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "检索问句或关键词"},
                },
                "required": ["query"],
            },
            domains=frozenset({"chat", "memory"}),
            handler=handle_memory_search,
            capabilities=_READ_ONLY | frozenset({ToolCapability.REQUIRES_GROUP_CONTEXT.value}),
        )
    )
    register_tool(
        LlmToolSpec(
            name="memory.save",
            description="把一条值得长期记住的群内事实写入记忆（勿保存闲聊情绪）。",
            parameters={
                "type": "object",
                "properties": {
                    "content": {"type": "string", "description": "要记住的短事实"},
                },
                "required": ["content"],
            },
            domains=frozenset({"chat", "memory"}),
            handler=handle_memory_save,
            capabilities=_SIDE_EFFECT,
        )
    )


async def handle_memory_search(arguments: dict[str, Any], context: ToolInvokeContext | None = None) -> dict[str, Any]:
    cfg = get_llm_config()
    if not cfg.llm_memory_rag_enabled or not can_read_persistent_memory(cfg) or not is_llm_memory_store_available():
        return {"ok": False, "error": "memory_disabled"}
    query = str((arguments or {}).get("query") or "").strip()
    if not query:
        return {"ok": False, "error": "query_required"}
    bot_id = int(getattr(context, "bot_id", 0) or 0) if context is not None else 0
    group_id = getattr(context, "group_id", None) if context is not None else None
    if bot_id <= 0:
        return {"ok": False, "error": "bot_context_required"}
    hits = await retrieve_memory_hits(bot_id, group_id, query, cfg=cfg)
    return {
        "ok": True,
        "hits": [
            {
                "content": str(item.get("content") or ""),
                "score": int(item.get("score") or 0),
                "source": str(item.get("source") or ""),
            }
            for item in hits
        ],
    }


async def handle_memory_save(arguments: dict[str, Any], context: ToolInvokeContext | None = None) -> dict[str, Any]:
    cfg = get_llm_config()
    if not cfg.llm_memory_rag_enabled or not is_llm_memory_store_available():
        return {"ok": False, "error": "memory_disabled"}
    content = str((arguments or {}).get("content") or "").strip()
    if not content:
        return {"ok": False, "error": "content_required"}
    bot_id = int(getattr(context, "bot_id", 0) or 0) if context is not None else 0
    group_id = getattr(context, "group_id", None) if context is not None else None
    if bot_id <= 0 or group_id is None:
        return {
            "ok": False,
            "error": "group_context_required",
            "message": "memory.save 仅在群聊上下文可用，私聊请勿调用",
        }
    ok = await save_memory_entry(bot_id, int(group_id), content, source="teach", cfg=cfg)
    return {"ok": bool(ok)}
