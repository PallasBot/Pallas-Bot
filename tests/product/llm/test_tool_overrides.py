from __future__ import annotations

from pallas.product.llm.tools.overrides import (
    clear_tool_description_overrides_cache,
    effective_tool_hints,
    load_tool_overrides,
    upsert_tool_override,
)
from pallas.product.llm.tools.registry import LlmToolSource, LlmToolSpec


def test_upsert_tool_override_hints_and_visibility(tmp_path, monkeypatch) -> None:
    clear_tool_description_overrides_cache()
    monkeypatch.setattr(
        "pallas.product.llm.tools.overrides.overrides_file_path",
        lambda: tmp_path / "llm_tool_overrides.json",
    )
    entry = upsert_tool_override(
        "sing.request_song",
        {"hints": ["放首", "来首"], "visibility": "deferred", "disabled": False},
    )
    assert entry["hints"] == ["放首", "来首"]
    assert entry["visibility"] == "deferred"
    loaded = load_tool_overrides()
    assert "sing.request_song" in loaded
    spec = LlmToolSpec(
        name="sing.request_song",
        description="点歌",
        parameters={},
        domains=frozenset({"sing"}),
        handler=lambda *_a, **_k: {},
        source=LlmToolSource.PLUGIN_COMMAND,
        hints=frozenset({"点歌"}),
        visibility="visible",
    )
    assert effective_tool_hints(spec) == frozenset({"放首", "来首"})
