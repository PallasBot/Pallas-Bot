from __future__ import annotations

from pallas.product.llm.config import LlmConfig
from pallas.product.llm.webui_config import LlmWebuiConfig, get_llm_webui_config


def test_llm_webui_config_hides_retired_repeater_assist() -> None:
    retired = {
        "llm_repeater_mode",
        "llm_repeater_group_cooldown_sec",
        "llm_repeater_strong_cooldown_sec",
        "llm_repeater_strong_attempt_rate",
        "llm_repeater_max_inflight",
        "llm_repeater_global_rpm",
        "llm_output_filter_polish_lite_hard_phrases",
        "llm_output_filter_polish_lite_soft_phrases",
    }
    assert retired.isdisjoint(LlmWebuiConfig.model_fields)


def test_llm_webui_config_defaults_current_turn_model_decision_on() -> None:
    config = LlmWebuiConfig()
    assert config.llm_current_turn_decision_enabled is True
    assert config.llm_current_turn_decision_model == ""


def test_get_llm_webui_config_keeps_saved_persona_output_firewall(monkeypatch) -> None:
    saved_policy = {
        "version": 1,
        "enabled": True,
        "severity": "soft",
        "strategy": "fallback",
        "max_retries": 0,
    }
    monkeypatch.setattr(
        "pallas.product.llm.webui_config.get_llm_config",
        lambda: LlmConfig(llm_persona_output_firewall=saved_policy),
    )

    assert get_llm_webui_config().llm_persona_output_firewall == saved_policy
