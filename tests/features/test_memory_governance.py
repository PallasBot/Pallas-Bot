from __future__ import annotations

from pallas.product.llm.config import LlmConfig, clear_llm_config_cache
from pallas.product.llm.kernel.memory_governance import (
    can_read_behavioral_learning,
    can_read_generic_knowledge,
    can_read_persistent_memory,
    can_read_runtime_state,
    can_write_runtime_state_summary,
    resolve_memory_read_policy,
    runtime_state_summary_metadata,
)


def test_can_read_runtime_state_requires_session_enabled() -> None:
    cfg = LlmConfig(llm_chat_enabled=True, llm_session_enabled=False)
    assert can_read_runtime_state(cfg) is False
    assert can_write_runtime_state_summary(cfg) is False
    assert runtime_state_summary_metadata(cfg) is None


def test_can_read_generic_knowledge_requires_enabled_flag() -> None:
    assert can_read_generic_knowledge(LlmConfig(llm_chat_enabled=True, llm_knowledge_sources_enabled=True)) is True
    assert can_read_generic_knowledge(LlmConfig(llm_chat_enabled=False, llm_knowledge_sources_enabled=True)) is False
    assert can_read_generic_knowledge(LlmConfig(llm_chat_enabled=True, llm_knowledge_sources_enabled=False)) is False


def test_can_read_persistent_memory_requires_rag_or_relationship() -> None:
    cfg = LlmConfig(
        llm_chat_enabled=True,
        llm_memory_rag_enabled=False,
        llm_relationship_notes_enabled=False,
    )
    assert can_read_persistent_memory(cfg) is False
    cfg = LlmConfig(
        llm_chat_enabled=True,
        llm_memory_rag_enabled=True,
        llm_relationship_notes_enabled=False,
    )
    assert can_read_persistent_memory(cfg) is True


def test_runtime_state_summary_metadata_disabled_when_summary_off() -> None:
    cfg = LlmConfig(
        llm_chat_enabled=True,
        llm_session_enabled=True,
        llm_session_summary_enabled=False,
    )
    assert can_write_runtime_state_summary(cfg) is False
    assert runtime_state_summary_metadata(cfg) is None


def test_runtime_state_summary_metadata_includes_thresholds() -> None:
    cfg = LlmConfig(
        llm_chat_enabled=True,
        llm_session_enabled=True,
        llm_session_summary_enabled=True,
        llm_session_summary_threshold=32,
        llm_session_summary_keep_messages=8,
    )
    meta = runtime_state_summary_metadata(cfg)
    assert meta == {"enabled": True, "threshold": 32, "keep_messages": 8}


def test_behavioral_learning_disabled_without_bias() -> None:
    clear_llm_config_cache()
    policy = resolve_memory_read_policy(LlmConfig(llm_chat_enabled=True, llm_repeater_bias_enabled=False))
    assert policy.allow_behavioral_learning is False
    assert can_read_behavioral_learning(LlmConfig(llm_chat_enabled=True, llm_repeater_bias_enabled=False)) is False
