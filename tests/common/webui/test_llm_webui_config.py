from __future__ import annotations

from pallas.product.llm.config import LlmConfig
from pallas.product.llm.webui_config import LlmWebuiConfig, get_llm_webui_config, normalize_repeater_mode_for_webui


def test_normalize_repeater_mode_for_webui_maps_legacy_modes() -> None:
    assert normalize_repeater_mode_for_webui("polish") == "select_polish_lite"
    assert normalize_repeater_mode_for_webui("both") == "select_fallback"


def test_normalize_repeater_mode_for_webui_keeps_supported_modes() -> None:
    assert normalize_repeater_mode_for_webui("select") == "select"
    assert normalize_repeater_mode_for_webui("select_polish_lite") == "select_polish_lite"
    assert normalize_repeater_mode_for_webui("off") == "off"


def test_normalize_repeater_mode_for_webui_unknown_defaults_select_polish_lite() -> None:
    assert normalize_repeater_mode_for_webui("unknown") == "select_polish_lite"


def test_llm_webui_config_defaults_to_select_polish_lite() -> None:
    assert LlmWebuiConfig().llm_repeater_mode == "select_polish_lite"


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
