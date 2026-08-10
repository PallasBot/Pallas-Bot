from __future__ import annotations

from types import SimpleNamespace

import pytest

from pallas.product.llm.repeater_capabilities import resolve_repeater_capabilities


@pytest.mark.parametrize(
    "mode",
    [
        "off",
        "select",
        "select_polish_lite",
        "select_fallback",
        "fallback",
        "polish",
        "both",
    ],
)
def test_resolve_repeater_capabilities_disables_retired_modes(monkeypatch, mode: str) -> None:
    capabilities = resolve_repeater_capabilities(
        SimpleNamespace(llm_chat_enabled=True, llm_repeater_mode=mode, llm_select_enabled=True)
    )

    assert capabilities.mode == "off"
    assert capabilities.select_enabled is False


def test_resolve_repeater_capabilities_blocks_stages_when_llm_disabled(monkeypatch) -> None:
    capabilities = resolve_repeater_capabilities(SimpleNamespace(llm_chat_enabled=False))

    assert capabilities.llm_enabled is False
    assert capabilities.select_enabled is False


def test_resolve_repeater_capabilities_uses_config_snapshot(monkeypatch) -> None:
    capabilities = resolve_repeater_capabilities(
        SimpleNamespace(
            llm_chat_enabled=True,
            llm_repeater_mode="off",
            llm_fallback_enabled=False,
            llm_polish_enabled=False,
            llm_select_enabled=False,
            llm_polish_lite_enabled=False,
        )
    )

    assert capabilities.mode == "off"
    assert capabilities.select_enabled is False
