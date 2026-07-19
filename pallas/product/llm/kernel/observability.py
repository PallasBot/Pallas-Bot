"""Read-only observability helpers for conversation kernel rollout."""

from __future__ import annotations

from typing import Any

from pallas.product.llm.config import LlmConfig, get_llm_config
from pallas.product.llm.kernel.memory_governance import (
    can_apply_feedback_bias,
    can_collect_feedback,
    can_promote_writeback,
    can_read_behavioral_learning,
    can_read_generic_knowledge,
    can_read_persistent_memory,
    can_read_runtime_state,
    can_write_runtime_state_summary,
    resolve_conversation_feature_level,
    resolve_memory_read_policy,
)


def build_conversation_kernel_status(cfg: LlmConfig | None = None) -> dict[str, Any]:
    c = cfg or get_llm_config()
    feature_level = resolve_conversation_feature_level(c)
    policy = resolve_memory_read_policy(c)
    runtime_summary_active = can_write_runtime_state_summary(c)
    return {
        "feature_level": feature_level.value,
        "llm_chat_enabled": bool(c.llm_chat_enabled),
        "conversation_feature_level_raw": str(c.conversation_feature_level or "").strip(),
        "llm_repeater_mode": str(c.llm_repeater_mode or "").strip(),
        "llm_repeater_feedback_enabled": bool(c.llm_repeater_feedback_enabled),
        "llm_repeater_bias_enabled": bool(c.llm_repeater_bias_enabled),
        "llm_repeater_writeback_enabled": bool(c.llm_repeater_writeback_enabled),
        "feedback_collect_active": can_collect_feedback(c),
        "feedback_bias_active": can_apply_feedback_bias(c),
        "writeback_active": can_promote_writeback(c),
        "runtime_state_summary_active": runtime_summary_active,
        "generic_knowledge_active": can_read_generic_knowledge(c),
        "memory_policy": {
            **policy.model_dump(mode="json"),
            "runtime_state_summary_enabled": runtime_summary_active,
            "read_session": can_read_runtime_state(c),
            "read_group_style": policy.allow_corpus_foundation,
            "read_affect": can_read_behavioral_learning(c),
            "write_session": runtime_summary_active,
            "read_persistent_memory": can_read_persistent_memory(c),
            "read_generic_knowledge": can_read_generic_knowledge(c),
        },
    }


def list_recent_conversation_traces(
    *,
    group_id: int | None = None,
    bot_id: int | None = None,
    kind: str | None = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    from packages.repeater.opportunity_trace import read_recent_repeater_opportunity_trace

    rows = read_recent_repeater_opportunity_trace(limit=max(int(limit) * 4, 200))
    filtered: list[dict[str, Any]] = []
    for row in reversed(rows):
        if group_id is not None and int(row.get("group_id") or 0) != int(group_id):
            continue
        if bot_id is not None and int(row.get("bot_id") or 0) != int(bot_id):
            continue
        row_kind = str(row.get("kind") or "").strip()
        if kind == "decision" and row_kind != "conversation_decision_trace":
            continue
        if kind and kind != "decision" and row_kind != kind:
            continue
        filtered.append(dict(row))
        if len(filtered) >= max(1, int(limit)):
            break
    return filtered
