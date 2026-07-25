from types import SimpleNamespace

from packages.help.help_tags import (
    normalize_help_tag,
    plugin_help_tag,
    resolve_plugin_help_tag,
)


def test_plugin_help_tag_from_metadata() -> None:
    plugin = SimpleNamespace(name="drink", metadata=SimpleNamespace(extra={"help_tag": "fun"}))
    assert plugin_help_tag(plugin) == "fun"


def test_resolve_plugin_help_tag_prefers_overrides() -> None:
    plugin = SimpleNamespace(name="drink", metadata=SimpleNamespace(extra={"help_tag": "fun"}))
    assert resolve_plugin_help_tag(plugin, overrides={"drink": "tool"}) == "tool"
    assert resolve_plugin_help_tag(plugin, overrides={}) == "fun"


def test_resolve_plugin_help_tag_legacy_name() -> None:
    plugin = SimpleNamespace(name="ollama", metadata=SimpleNamespace(extra={"help_tag": "chat"}))
    assert resolve_plugin_help_tag(plugin, overrides={"llm_chat": "ai"}) == "ai"


def test_resolve_plugin_help_tag_by_module_package() -> None:
    plugin = SimpleNamespace(
        name="牛牛复读",
        module=SimpleNamespace(__name__="packages.repeater"),
        metadata=SimpleNamespace(extra={"help_tag": "fun"}),
    )
    assert resolve_plugin_help_tag(plugin, overrides={"repeater": "tool"}) == "tool"


def test_normalize_help_tag_blank() -> None:
    assert normalize_help_tag("") == "other"
    assert normalize_help_tag("  FUN ") == "fun"
