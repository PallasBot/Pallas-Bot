from __future__ import annotations

from types import SimpleNamespace

import pytest

from pallas.product.llm.tools.bootstrap import reset_llm_tools_bootstrap_for_tests
from pallas.product.llm.tools.command_invoke import CommandTemplateError, render_command_template
from pallas.product.llm.tools.declare import llm_command_tool_row
from pallas.product.llm.tools.metadata import parse_llm_command_tool_decl
from pallas.product.llm.tools.plugin_bootstrap import build_command_tool_spec, register_plugin_command_tools
from pallas.product.llm.tools.registry import clear_tool_registry, tool_openai_schemas


@pytest.fixture(autouse=True)
def reset_tools() -> None:
    reset_llm_tools_bootstrap_for_tests()
    yield
    reset_llm_tools_bootstrap_for_tests()


def test_render_command_template() -> None:
    text = render_command_template("牛牛画画 {prompt}", {"prompt": "一只猫"})
    assert text == "牛牛画画 一只猫"


def test_render_command_template_missing_field() -> None:
    with pytest.raises(CommandTemplateError):
        render_command_template("牛牛画画 {prompt}", {})


def test_parse_llm_command_tool_decl() -> None:
    raw = llm_command_tool_row(
        name="draw.image",
        command_id="draw.draw",
        description="生图",
        parameters={"type": "object", "properties": {}},
        command_template="牛牛画画 {prompt}",
    )
    decl = parse_llm_command_tool_decl(raw)
    assert decl is not None
    assert decl.name == "draw.image"


def test_register_plugin_command_tool_schema(monkeypatch) -> None:
    decl = parse_llm_command_tool_decl(
        llm_command_tool_row(
            name="demo.echo",
            command_id="demo.echo",
            description="回声",
            parameters={
                "type": "object",
                "properties": {"text": {"type": "string"}},
                "required": ["text"],
            },
            command_template="echo {text}",
        )
    )
    assert decl is not None

    class FakePlugin:
        name = "demo"
        metadata = SimpleNamespace(
            name="演示",
            extra={
                "llm_tools": [
                    llm_command_tool_row(
                        name="demo.echo",
                        command_id="demo.echo",
                        description="回声",
                        parameters={
                            "type": "object",
                            "properties": {"text": {"type": "string"}},
                            "required": ["text"],
                        },
                        command_template="echo {text}",
                    )
                ]
            },
        )

    monkeypatch.setattr(
        "nonebot.get_loaded_plugins",
        lambda: [FakePlugin()],
    )
    clear_tool_registry()
    count = register_plugin_command_tools()
    assert count == 1
    schemas = tool_openai_schemas()
    names = {item["function"]["name"] for item in schemas}
    assert "demo.echo" in names


def test_build_command_tool_spec_requires_context() -> None:
    decl = parse_llm_command_tool_decl(
        llm_command_tool_row(
            name="demo.echo",
            command_id="demo.echo",
            description="回声",
            parameters={"type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"]},
            command_template="echo {text}",
        )
    )
    assert decl is not None
    spec = build_command_tool_spec(decl, plugin_name="demo", plugin_title="演示")
    import asyncio

    result = asyncio.run(spec.handler({"text": "hi"}, None))
    assert result["ok"] is False
    assert result["error"] == "missing_invoke_context"
