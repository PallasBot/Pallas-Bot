from __future__ import annotations

import pytest

from packages.llm_chat import __plugin_meta__
from pallas.product.llm.tools.bootstrap import reset_llm_tools_bootstrap_for_tests
from pallas.product.llm.tools.plugin_bootstrap import register_plugin_command_tools
from pallas.product.llm.tools.registry import clear_tool_registry, tool_openai_schemas


@pytest.fixture(autouse=True)
def reset_tools() -> None:
    reset_llm_tools_bootstrap_for_tests()
    clear_tool_registry()
    yield
    reset_llm_tools_bootstrap_for_tests()
    clear_tool_registry()


def test_llm_chat_clear_tool_registers(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakePlugin:
        name = "llm_chat"

        metadata = __plugin_meta__

    monkeypatch.setattr("nonebot.get_loaded_plugins", lambda: [FakePlugin()])
    count = register_plugin_command_tools()
    assert count >= 1
    names = {item["function"]["name"] for item in tool_openai_schemas()}
    assert "llm_chat.clear" in names
