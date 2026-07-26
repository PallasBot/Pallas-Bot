from __future__ import annotations

from pallas.product.llm.assembler import assemble_tool_bundle


def test_assemble_tool_bundle_adds_direct_chat_stage_plan(monkeypatch) -> None:
    monkeypatch.setattr(
        "pallas.product.llm.tools.registry.tool_metadata_for_chat",
        lambda **kwargs: {"tools_enabled": True, "tool_schemas": [{"name": "search"}]},
    )

    bundle = assemble_tool_bundle(task="llm_chat", user_text="查资料")

    assert bundle["agent_stage_plan"] == ["plan", "tool_loop", "generate"]
    assert bundle["tool_schema_count"] == 1


def test_assemble_tool_bundle_reuses_precomputed_metadata(monkeypatch) -> None:
    monkeypatch.setattr(
        "pallas.product.llm.tools.registry.tool_metadata_for_chat",
        lambda **kwargs: (_ for _ in ()).throw(AssertionError("should not resolve twice")),
    )

    bundle = assemble_tool_bundle(
        task="llm_chat",
        user_text="查资料",
        tool_metadata={"tools_enabled": False, "tool_schemas": []},
    )

    assert bundle["agent_stage_plan"] == ["generate"]
    assert bundle["tool_schema_count"] == 0
