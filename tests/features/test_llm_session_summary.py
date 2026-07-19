from __future__ import annotations

from pallas.product.llm.config import LlmConfig


def test_llm_session_summary_config_defaults() -> None:
    cfg = LlmConfig()
    assert cfg.llm_session_summary_enabled is True
    assert cfg.llm_session_summary_threshold == 40
    assert cfg.llm_session_summary_keep_messages == 16
