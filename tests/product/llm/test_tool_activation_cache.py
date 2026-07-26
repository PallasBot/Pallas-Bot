from __future__ import annotations

from pallas.product.llm.tools.activation_cache import (
    activated_tool_names,
    clear_activation_cache_for_tests,
    remember_activated_tools,
)


def test_activated_tools_expire(monkeypatch) -> None:
    import pallas.product.llm.tools.activation_cache as cache

    clear_activation_cache_for_tests()
    now = [100.0]
    monkeypatch.setattr(cache.time, "monotonic", lambda: now[0])
    remember_activated_tools(1, 2, 3, ["music.play"])
    assert activated_tool_names(1, 2, 3) == ["music.play"]

    now[0] += 601
    assert activated_tool_names(1, 2, 3) == []
