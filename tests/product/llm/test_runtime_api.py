from __future__ import annotations


def test_runtime_api_omits_retired_repeater_capabilities() -> None:
    from pallas.product.llm import runtime_api

    assert not hasattr(runtime_api, "resolve_repeater_capabilities")
