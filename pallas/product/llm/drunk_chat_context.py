"""酒后聊天与 llm_chat 共用的 system prompt 组装。"""

from __future__ import annotations

from dataclasses import dataclass

from nonebot import logger

from pallas.core.foundation.db import make_group_config_repository
from pallas.product.persona.compile_persona_prompt import load_base_system_prompt
from pallas.product.persona.expression_habits import build_expression_habits_suffix

from .config import LlmConfig, get_llm_config
from .knowledge.inject import enrich_system_with_knowledge_sources
from .memory.inject import enrich_system_with_memory_context, enrich_system_with_relationship_context
from .persona_context import build_persona_llm_context


@dataclass(frozen=True)
class DrunkChatSubmitContext:
    system_prompt: str
    token_count: int | None
    temperature: float | None = None


def resolve_llm_chat_custom_system_path() -> str | None:
    try:
        from packages.llm_chat.config import get_llm_chat_config

        path = str(get_llm_chat_config().llm_chat_system_prompt_path or "").strip()
        return path or None
    except Exception:
        return None


async def build_group_expression_suffix(group_id: int | None) -> str:
    if group_id is None:
        return ""
    try:
        group_config = await make_group_config_repository().get(int(group_id))
    except Exception:
        return ""
    profile = getattr(group_config, "style_profile", None) if group_config is not None else None
    return build_expression_habits_suffix(profile if isinstance(profile, dict) else None)


async def build_drunk_chat_system_prompt(
    bot_id: int,
    group_id: int | None,
    user_text: str,
    *,
    user_id: int | None = None,
    base_system_path: str | None = None,
    cfg: LlmConfig | None = None,
) -> DrunkChatSubmitContext | None:
    """与 llm_chat 同一套牛格编译；mode=drunk 时附加醉酒 overlay。"""
    llm_cfg = cfg or get_llm_config()
    resolved_path = base_system_path if base_system_path is not None else resolve_llm_chat_custom_system_path()
    temperature: float | None = None
    token_count: int | None = None
    system_prompt = ""

    try:
        bundle, temperature, token_count = await build_persona_llm_context(
            bot_id,
            group_id,
            user_text,
            mode="drunk",
            purpose="chat",
            base_system_path=resolved_path,
        )
        system_prompt = bundle.system.strip()
    except Exception:
        logger.exception("build_drunk_chat_system_prompt: compile persona failed bot={} group={}", bot_id, group_id)

    if not system_prompt:
        system_prompt = load_base_system_prompt(custom_path=resolved_path).strip()
    if not system_prompt:
        return None

    memory_result = await enrich_system_with_memory_context(
        system_prompt,
        bot_id=bot_id,
        group_id=group_id,
        query_text=user_text,
        cfg=llm_cfg,
    )
    system_prompt = memory_result.system_prompt

    knowledge_result = await enrich_system_with_knowledge_sources(
        system_prompt,
        bot_id=bot_id,
        group_id=group_id,
        user_id=user_id,
        query_text=user_text,
        cfg=llm_cfg,
    )
    system_prompt = knowledge_result.system_prompt

    relationship_result = await enrich_system_with_relationship_context(
        system_prompt,
        bot_id=bot_id,
        group_id=group_id,
        user_id=user_id,
        cfg=llm_cfg,
    )
    system_prompt = relationship_result.system_prompt

    expression_suffix = await build_group_expression_suffix(group_id)
    if expression_suffix:
        system_prompt = f"{system_prompt.rstrip()}\n{expression_suffix}"

    return DrunkChatSubmitContext(
        system_prompt=system_prompt,
        token_count=token_count,
        temperature=temperature,
    )
