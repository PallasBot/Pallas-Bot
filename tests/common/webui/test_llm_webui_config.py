from __future__ import annotations

from pallas.product.llm.webui_config import normalize_repeater_mode_for_webui


def test_normalize_repeater_mode_for_webui_maps_legacy_modes() -> None:
    assert normalize_repeater_mode_for_webui("polish") == "select_polish_lite"
    assert normalize_repeater_mode_for_webui("both") == "select_fallback"


def test_normalize_repeater_mode_for_webui_keeps_supported_modes() -> None:
    assert normalize_repeater_mode_for_webui("select") == "select"
    assert normalize_repeater_mode_for_webui("select_polish_lite") == "select_polish_lite"
    assert normalize_repeater_mode_for_webui("off") == "off"


def test_normalize_repeater_mode_for_webui_unknown_defaults_select() -> None:
    assert normalize_repeater_mode_for_webui("unknown") == "select"
