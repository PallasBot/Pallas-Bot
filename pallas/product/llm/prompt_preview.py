"""Build a deterministic, source-labelled preview of the chat system prompt."""

from __future__ import annotations

from typing import Any

from pallas.product.llm.assembler.chat_prompt import ChatPromptAssembler, ResolvedGroupExpression
from pallas.product.llm.assembler.context import ChatContextBundle, assemble_direct_chat_context
from pallas.product.llm.assembler.prompt_overrides import load_prompt_overrides
from pallas.product.llm.config import get_llm_config
from pallas.product.llm.persona_context import build_persona_llm_context
from pallas.product.llm.repeater_semantic_style import (
    resolve_cached_semantic_style,
    semantic_style_injection_enabled,
)
from pallas.product.llm.reply_shape import resolve_reply_shape
from pallas.product.llm.tools.time_now import current_time_text
from pallas.product.llm.turn_policy import TurnPolicy

_SECTION_META = (
    ("injection_guard", "安全边界", "persona.prompt_guard"),
    ("persona", "核心人设", "persona.compile_persona_prompt"),
    ("identity", "自我身份", "persona.self_identity"),
    ("reply_shape", "回复形状与输出契约", "llm.reply_shape"),
    ("turn_policy", "本轮策略", "llm.turn_policy"),
    ("current_time", "当前时间", "llm.tools.time_now"),
    ("group_timeline", "群聊上下文", "llm.assembler.context"),
    ("memory", "长期记忆", "llm.assembler.context"),
    ("knowledge", "知识检索", "llm.assembler.context"),
    ("relationship", "关系上下文", "llm.assembler.context"),
    ("person_facts", "人物事实", "llm.assembler.context"),
    ("mid_term", "中期摘要", "llm.assembler.context"),
    ("group_expression", "群表达指导", "llm.assembler.chat_prompt"),
    ("behavior_reference", "真人接话参考", "llm.assembler.chat_prompt"),
    ("tool_context", "工具上下文", "preview（默认关闭）"),
)


async def build_prompt_preview(
    *,
    bot_id: int,
    group_id: int | None,
    user_id: int,
    query_text: str,
) -> dict[str, Any]:
    bundle, _, _ = await build_persona_llm_context(bot_id, group_id, query_text)
    context = await assemble_direct_chat_context(
        bot_id=bot_id,
        group_id=group_id,
        user_id=user_id,
        query_text=query_text,
        cfg=get_llm_config(),
        allow_persistent_memory=True,
        group_timeline="",
    )
    if not isinstance(context, ChatContextBundle):
        context = ChatContextBundle(
            memory=str(getattr(context, "system_prompt", "") or ""),
            stage_durations_ms=dict(getattr(context, "stage_durations_ms", {}) or {}),
        )

    policy = TurnPolicy(
        reply_target="answer",
        seriousness="serious",
        social_action="none",
        allow_teasing=False,
        allow_affection=False,
        needs_tool=False,
        needs_grounding=True,
    )
    group_expression_profile = None
    try:
        from pallas.product.persona.model import ResolvedPersona

        persona_raw = getattr(bundle.metadata, "persona", None)
        if isinstance(persona_raw, dict):
            group_expression_profile = ResolvedPersona(**persona_raw).group_expression_profile
    except Exception:
        group_expression_profile = None

    semantic_style = None
    semantic_style_trace = {
        "bypassed_injection_gate": False,
        "would_inject": False,
    }
    if group_id is not None:
        request_id = f"preview:{bot_id}:{group_id}:{user_id}"
        semantic_style_trace = {
            "bypassed_injection_gate": True,
            "would_inject": semantic_style_injection_enabled(request_id, bot_id=bot_id, group_id=group_id),
        }
        semantic_style = resolve_cached_semantic_style(
            bot_id,
            group_id,
            "group_chat",
            request_id=request_id,
            query_text=query_text,
            recent_assistant_replies=(),
            bypass_injection_gate=True,
        )
    group_expression = ResolvedGroupExpression(
        matched_examples=[
            (str(example[0] or ""), str(example[1] or ""))
            for example in (getattr(semantic_style, "matched_examples", None) or [])[:2]
            if isinstance(example, (list, tuple)) and len(example) == 2
        ],
        baseline_note=str(getattr(semantic_style, "baseline_note", "") or ""),
        behavior_strategies=[
            (
                str(item.scene or ""),
                str(item.action or ""),
                str(item.outcome or ""),
            )
            for item in (getattr(semantic_style, "behavior_strategies", None) or [])[:2]
            if str(getattr(item, "scene", "") or "").strip() and str(getattr(item, "action", "") or "").strip()
        ],
    )
    reply_shape = resolve_reply_shape(policy, group_expression_profile)
    section_overrides = load_prompt_overrides(bot_id=bot_id, group_id=group_id) if group_id is not None else {}
    sections = ChatPromptAssembler().section_texts(
        core_persona=str(getattr(bundle.sections, "base", "") or ""),
        self_identity=str(getattr(bundle.sections, "self_identity", "") or ""),
        turn_policy=policy,
        context=context,
        group_expression=group_expression,
        reply_shape=reply_shape,
        current_time=current_time_text(),
        tool_context=None,
        section_overrides=section_overrides,
    )
    section_ids = [item[0] for item in _SECTION_META]
    prompt_sections = []
    for section_id, (_, title, source), content in zip(section_ids, _SECTION_META, sections, strict=False):
        prompt_sections.append({
            "id": section_id,
            "title": title,
            "source": source,
            "active": bool(str(content).strip()),
            "content": str(content).strip(),
            "override": section_overrides.get(section_id),
        })
    active_sections = [section for section in prompt_sections if section["active"]]
    return {
        "preview_mode": True,
        "decision_source": "preview_default",
        "bot_id": bot_id,
        "group_id": group_id,
        "user_id": user_id,
        "query_text": query_text,
        "sections": prompt_sections,
        "system_prompt": ChatPromptAssembler._join_unique([section["content"] for section in active_sections]),
        "traces": {
            "stage_durations_ms": context.stage_durations_ms,
            "knowledge_retrieval": context.knowledge_retrieval_trace,
            "hybrid_retrieval": context.hybrid_retrieval_trace,
            "relationship": context.relationship_trace,
            "semantic_style": semantic_style_trace,
        },
    }
