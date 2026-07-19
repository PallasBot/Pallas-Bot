from __future__ import annotations

from pallas.product.llm.config import LlmConfig
from pallas.product.llm.legacy_guard import assess_legacy_chat_submit, is_legacy_ollama_endpoint


def test_is_legacy_ollama_endpoint() -> None:
    assert is_legacy_ollama_endpoint("/api/ollama/chat") is True
    assert is_legacy_ollama_endpoint("/api/v1/chat/completions") is False


def test_assess_legacy_chat_submit_blocks_without_allow() -> None:
    cfg = LlmConfig(use_unified_chat_api=False, legacy_chat_allowed=False)
    assert assess_legacy_chat_submit(cfg) == "legacy_chat_disabled"


def test_assess_legacy_chat_submit_allows_ollama_when_legacy_allowed() -> None:
    cfg = LlmConfig(
        use_unified_chat_api=False,
        legacy_chat_allowed=True,
        legacy_chat_endpoint="/api/ollama/chat",
    )
    assert assess_legacy_chat_submit(cfg) is None


def test_assess_legacy_chat_submit_blocks_ollama_without_allow() -> None:
    cfg = LlmConfig(
        use_unified_chat_api=False,
        legacy_chat_allowed=False,
        legacy_chat_endpoint="/api/ollama/chat",
    )
    assert assess_legacy_chat_submit(cfg) == "legacy_ollama_blocked"
