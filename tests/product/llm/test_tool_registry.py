from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from pallas.product.llm.tools import registry


async def _echo_handler(args: dict, _ctx) -> dict[str, object]:
    return {"value": args.get("message", "")}


def _patch_tool_runtime(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(registry, "ensure_tools_loaded", lambda: None)
    monkeypatch.setattr(
        registry,
        "get_llm_config",
        lambda: SimpleNamespace(
            llm_tools_enabled=True,
            llm_tools_blacklist=[],
            llm_tools_desc_max_len=120,
            llm_tools_selective=False,
        ),
    )
    monkeypatch.setattr(
        registry,
        "get_arknights_kb_config",
        lambda: SimpleNamespace(arknights_kb_enabled=True),
    )
    monkeypatch.setattr(registry, "load_tool_description_overrides", dict)


@pytest.fixture(autouse=True)
def restore_global_tool_registry() -> None:
    yield
    from pallas.product.llm.tools.bootstrap import ensure_llm_tools_bootstrapped, reset_llm_tools_bootstrap_for_tests

    reset_llm_tools_bootstrap_for_tests()
    ensure_llm_tools_bootstrapped()


def _make_spec(
    *,
    name: str = "test.echo",
    domains: frozenset[str] | None = None,
    source=None,
) -> object:
    return registry.LlmToolSpec(
        name=name,
        description=f"{name} description",
        parameters={"type": "object", "properties": {"message": {"type": "string"}}},
        domains=domains or frozenset({"test"}),
        handler=_echo_handler,
        source=source or registry.LlmToolSource.BUILTIN,
    )


def test_register_tool_deduplicates_by_name(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_tool_runtime(monkeypatch)
    registry.clear_tool_registry()
    spec = _make_spec()
    registry.register_tool(spec)
    registry.register_tool(spec)

    schemas = registry.tool_openai_schemas()

    assert len(schemas) == 1
    assert schemas[0]["function"]["name"] == "test.echo"


def test_iter_registered_tools_filters_by_source_and_domain(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_tool_runtime(monkeypatch)
    registry.clear_tool_registry()
    registry.register_tool(_make_spec(name="test.echo", domains=frozenset({"test"})))
    registry.register_tool(
        _make_spec(
            name="plugin.roll",
            domains=frozenset({"command", "dice"}),
            source=registry.LlmToolSource.PLUGIN_COMMAND,
        )
    )

    plugin_items = registry.iter_registered_tools(source=registry.LlmToolSource.PLUGIN_COMMAND)
    dice_items = registry.iter_registered_tools(domains=frozenset({"dice"}))

    assert [item.name for item in plugin_items] == ["plugin.roll"]
    assert [item.name for item in dice_items] == ["plugin.roll"]


def test_build_tools_ui_rows_exposes_source(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_tool_runtime(monkeypatch)
    registry.clear_tool_registry()
    registry.register_tool(
        _make_spec(
            name="plugin.roll",
            domains=frozenset({"command", "dice"}),
            source=registry.LlmToolSource.PLUGIN_COMMAND,
        )
    )

    rows = registry.build_tools_ui_rows()

    assert rows == [
        {
            "name": "plugin.roll",
            "description": "plugin.roll description",
            "domains": ["command", "dice"],
            "command_id": None,
            "source": "plugin_command",
        }
    ]


def test_execute_tool_async_normalizes_non_ok_dict(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_tool_runtime(monkeypatch)
    registry.clear_tool_registry()
    registry.register_tool(_make_spec())

    result = asyncio.run(registry.execute_tool_async("test.echo", {"message": "hi"}))

    assert result["ok"] is True
    assert result["result"] == {"value": "hi"}
    assert result["source"] == "builtin"
