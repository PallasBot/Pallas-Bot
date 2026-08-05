from __future__ import annotations

import pytest

from pallas.product.llm.config import LlmConfig, clear_llm_config_cache, get_llm_config


def test_strong_tier_config_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in (
        "LLM_REPEATER_STRONG_COOLDOWN_SEC",
        "LLM_REPEATER_STRONG_ATTEMPT_RATE",
        "LLM_SHARED_MAX_CONCURRENCY",
        "LLM_REPEATER_MAX_INFLIGHT",
        "LLM_REPEATER_GLOBAL_RPM",
        "LLM_REPEATER_FEEDBACK_ENABLED",
        "LLM_REPEATER_BIAS_ENABLED",
        "LLM_REPEATER_WRITEBACK_ENABLED",
    ):
        monkeypatch.delenv(key, raising=False)

    cfg = LlmConfig()

    assert cfg.llm_repeater_strong_cooldown_sec == 25
    assert cfg.llm_repeater_strong_attempt_rate == pytest.approx(0.55)
    assert cfg.llm_shared_max_concurrency == 4
    assert cfg.llm_repeater_max_inflight == 2
    assert cfg.llm_repeater_global_rpm == 18
    assert cfg.llm_repeater_feedback_enabled is True
    assert cfg.llm_repeater_bias_enabled is True
    assert cfg.llm_repeater_writeback_enabled is True


def test_strong_attempt_rate_is_clamped_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    clear_llm_config_cache()
    monkeypatch.setenv("LLM_REPEATER_STRONG_ATTEMPT_RATE", "2.5")

    cfg = get_llm_config()

    assert cfg.llm_repeater_strong_attempt_rate == 1.0
    clear_llm_config_cache()
