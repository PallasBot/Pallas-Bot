from __future__ import annotations

from .config import LlmConfig, get_llm_config, resolve_legacy_rwkv_drunk_chat_enabled


def is_llm_chat_service_enabled(cfg: LlmConfig | None = None) -> bool:
    """智能对话总开关（酒后 LLM 与随时 @ 共用）。

    内核模式下仅看 LLM_CHAT_ENABLED，不依赖 AI Runtime 可达。
    """
    return bool((cfg or get_llm_config()).llm_chat_enabled)


def is_llm_plugin_globally_disabled() -> bool:
    """llm_chat 插件是否被全实例禁用（含 ollama 等别名）。

    全实例禁用会在启动时跳过插件加载；此处兜底运行中热改名单与
    work/embed 辅进程，保证后台出口也停。
    """
    try:
        from packages.help.global_disable import resolve_global_disabled_plugin_names
        from packages.help.plugin_legacy_names import is_plugin_name_in_set

        return is_plugin_name_in_set("llm_chat", resolve_global_disabled_plugin_names())
    except Exception:
        return False


def llm_calls_enabled(cfg: LlmConfig | None = None) -> bool:
    """LLM 出口统一总闸：配置总开关开 且 llm_chat 插件未被全实例禁用。

    供 ``complete_chat_message`` / ``fetch_embeddings_sync`` 等底层出口兜底，
    覆盖不走消息入口的后台循环、work/embed 辅进程与线程。
    """
    c = cfg or get_llm_config()
    if not bool(getattr(c, "llm_chat_enabled", False)):
        return False
    return not is_llm_plugin_globally_disabled()


async def llm_plugin_disabled_for_scope(bot_id: int | None, group_id: int | None) -> bool:
    """运行时按牛/按群禁用 llm_chat（含全实例禁用与群白名单）。"""
    try:
        from packages.help.plugin_manager import is_plugin_disabled

        return await is_plugin_disabled("llm_chat", group_id=group_id, bot_id=bot_id)
    except Exception:
        return False


def is_legacy_rwkv_drunk_chat_enabled() -> bool:
    """遗留酒后 RWKV 开关（CHAT_ENABLE / chat_enable，与 LLM 总闸独立）。"""
    return resolve_legacy_rwkv_drunk_chat_enabled()


def is_drunk_chat_enabled(cfg: LlmConfig | None = None) -> bool:
    """酒后聊天是否可用（LLM 总闸或遗留 RWKV）。"""
    return is_llm_chat_service_enabled(cfg) or is_legacy_rwkv_drunk_chat_enabled()
