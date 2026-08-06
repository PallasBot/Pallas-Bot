from __future__ import annotations

from types import SimpleNamespace

import pytest

from pallas.product.llm.repeater_capabilities import resolve_repeater_capabilities


@pytest.mark.parametrize(
    ("mode", "expected_mode", "select_enabled"),
    [
        ("off", "off", False),
        ("select", "select", True),
        ("select_polish_lite", "select", True),
        ("select_fallback", "select", True),
        ("fallback", "select", True),
        ("polish", "select", True),
        ("both", "select", True),
    ],
)
def test_resolve_repeater_capabilities_normalizes_mode(
    monkeypatch, mode: str, expected_mode: str, select_enabled: bool
) -> None:
    monkeypatch.setattr("pallas.product.llm.repeater_capabilities.resolve_llm_repeater_mode", lambda: mode)
    monkeypatch.setattr(
        "pallas.product.llm.repeater_capabilities.resolve_llm_repeater_flags",
        lambda: (False, False, False),
    )

    capabilities = resolve_repeater_capabilities(SimpleNamespace(llm_chat_enabled=True))

    assert capabilities.mode == expected_mode
    assert capabilities.select_enabled is select_enabled


def test_resolve_repeater_capabilities_blocks_stages_when_llm_disabled(monkeypatch) -> None:
    monkeypatch.setattr("pallas.product.llm.repeater_capabilities.resolve_llm_repeater_mode", lambda: "select")
    monkeypatch.setattr(
        "pallas.product.llm.repeater_capabilities.resolve_llm_repeater_flags",
        lambda: (False, False, True),
    )

    capabilities = resolve_repeater_capabilities(SimpleNamespace(llm_chat_enabled=False))

    assert capabilities.llm_enabled is False
    assert capabilities.select_enabled is False


def test_resolve_repeater_capabilities_uses_config_snapshot(monkeypatch) -> None:
    monkeypatch.setattr("pallas.product.llm.repeater_capabilities.resolve_llm_repeater_mode", lambda: "select")
    monkeypatch.setattr(
        "pallas.product.llm.repeater_capabilities.resolve_llm_repeater_flags",
        lambda: (False, False, True),
    )

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
