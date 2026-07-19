"""Memory-learning asset taxonomy and governance gates."""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict

from pallas.product.llm.config import LlmConfig, get_llm_config

from .feedback_models import FeedbackBiasSnapshot
from .models import ConversationFeatureLevel


class MemoryAssetKind(StrEnum):
    RUNTIME_STATE = "runtime_conversation_state"
    PERSISTENT_MEMORY = "persistent_memory"
    CORPUS_FOUNDATION = "corpus_foundation"
    BEHAVIORAL_LEARNING = "behavioral_learning"
    GENERIC_KNOWLEDGE = "generic_knowledge"


class MemoryReadPolicy(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="ignore")

    allow_runtime_state: bool = True
    allow_persistent_memory: bool = True
    allow_corpus_foundation: bool = True
    allow_behavioral_learning: bool = False
    allow_generic_knowledge: bool = True
    allow_writeback: bool = False


def resolve_conversation_feature_level(cfg: LlmConfig | None = None) -> ConversationFeatureLevel:
    c = cfg or get_llm_config()
    raw = str(getattr(c, "conversation_feature_level", "") or "").strip().lower()
    if raw == ConversationFeatureLevel.LEGACY_REPEATER:
        return ConversationFeatureLevel.LEGACY_REPEATER
    if raw == ConversationFeatureLevel.REPEATER_PLUS_DECISION:
        return ConversationFeatureLevel.REPEATER_PLUS_DECISION
    if raw == ConversationFeatureLevel.FULL_CONVERSATION_KERNEL:
        return ConversationFeatureLevel.FULL_CONVERSATION_KERNEL
    if not c.llm_chat_enabled:
        return ConversationFeatureLevel.LEGACY_REPEATER
    if c.llm_repeater_feedback_enabled or c.llm_repeater_bias_enabled or c.llm_repeater_writeback_enabled:
        return ConversationFeatureLevel.FULL_CONVERSATION_KERNEL
    if c.llm_select_enabled or c.llm_polish_enabled or c.llm_fallback_enabled:
        return ConversationFeatureLevel.REPEATER_PLUS_DECISION
    return ConversationFeatureLevel.LEGACY_REPEATER


def resolve_memory_read_policy(cfg: LlmConfig | None = None) -> MemoryReadPolicy:
    c = cfg or get_llm_config()
    feature_level = resolve_conversation_feature_level(c)
    allow_behavioral = bool(c.llm_repeater_bias_enabled) and feature_level != ConversationFeatureLevel.LEGACY_REPEATER
    allow_writeback = bool(c.llm_repeater_writeback_enabled)
    if feature_level == ConversationFeatureLevel.LEGACY_REPEATER:
        allow_writeback = False
    return MemoryReadPolicy(
        allow_runtime_state=bool(c.llm_chat_enabled and c.llm_session_enabled),
        allow_persistent_memory=bool(
            c.llm_chat_enabled and (c.llm_memory_rag_enabled or c.llm_relationship_notes_enabled)
        ),
        allow_corpus_foundation=True,
        allow_behavioral_learning=allow_behavioral,
        allow_generic_knowledge=bool(c.llm_chat_enabled and c.llm_knowledge_sources_enabled),
        allow_writeback=allow_writeback,
    )


def can_read_runtime_state(cfg: LlmConfig | None = None) -> bool:
    return resolve_memory_read_policy(cfg).allow_runtime_state


def can_read_persistent_memory(cfg: LlmConfig | None = None) -> bool:
    return resolve_memory_read_policy(cfg).allow_persistent_memory


def can_read_behavioral_learning(cfg: LlmConfig | None = None) -> bool:
    return resolve_memory_read_policy(cfg).allow_behavioral_learning


def can_read_generic_knowledge(cfg: LlmConfig | None = None) -> bool:
    return resolve_memory_read_policy(cfg).allow_generic_knowledge


def can_write_runtime_state_summary(cfg: LlmConfig | None = None) -> bool:
    c = cfg or get_llm_config()
    if not can_read_runtime_state(c):
        return False
    return bool(c.llm_session_summary_enabled)


def runtime_state_summary_metadata(cfg: LlmConfig | None = None) -> dict[str, object] | None:
    c = cfg or get_llm_config()
    if not can_write_runtime_state_summary(c):
        return None
    return {
        "enabled": True,
        "threshold": c.llm_session_summary_threshold,
        "keep_messages": c.llm_session_summary_keep_messages,
    }


def can_collect_feedback(cfg: LlmConfig | None = None) -> bool:
    c = cfg or get_llm_config()
    return bool(c.llm_chat_enabled and c.llm_repeater_feedback_enabled)


def can_apply_feedback_bias(cfg: LlmConfig | None = None) -> bool:
    c = cfg or get_llm_config()
    policy = resolve_memory_read_policy(c)
    return bool(c.llm_chat_enabled and c.llm_repeater_bias_enabled and policy.allow_behavioral_learning)


def can_promote_writeback(cfg: LlmConfig | None = None) -> bool:
    c = cfg or get_llm_config()
    policy = resolve_memory_read_policy(c)
    return bool(c.llm_chat_enabled and c.llm_repeater_writeback_enabled and policy.allow_writeback)


def empty_bias_snapshot() -> FeedbackBiasSnapshot:
    return FeedbackBiasSnapshot()
