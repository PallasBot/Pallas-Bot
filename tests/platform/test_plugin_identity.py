from __future__ import annotations

from pallas.core.platform.bot_runtime.plugin_matrix import is_shard_internal_plugin
from pallas.core.platform.plugin_runtime.plugin_identity import (
    PluginIdentity,
    canonical_plugin_id,
    plugin_identity,
    plugin_identity_from_module,
)


def test_canonical_plugin_id_normalizes_legacy_and_module_names() -> None:
    assert canonical_plugin_id("community_stats") == "pb_stats"
    assert canonical_plugin_id("packages.pb_stats") == "pb_stats"
    assert canonical_plugin_id("pallas_plugin_bot_status") == "bot_status"
    assert canonical_plugin_id("packages.help") == "help"


def test_plugin_identity_returns_registry_metadata() -> None:
    ident = plugin_identity("relogin_bot")
    assert isinstance(ident, PluginIdentity)
    assert ident.plugin_id == "relogin_bot"
    assert ident.kind == "extra"
    assert ident.pip_module_prefix == "pallas_plugin_relogin_bot"
    assert ident.pip_package == "pallas-plugin-protocol"


def test_plugin_identity_from_module_prefers_direct_plugin_module() -> None:
    ident = plugin_identity_from_module("pallas_plugin_relogin_bot.service")
    assert ident.plugin_id == "relogin_bot"


def test_plugin_identity_marks_shard_internal_plugins() -> None:
    assert plugin_identity("relogin_forward").kind == "shard-internal"
    assert plugin_identity("maa_hub").kind == "shard-internal"
    assert plugin_identity("packages.maa_hub").kind == "shard-internal"
    assert plugin_identity("pallas_plugin_maa_hub").kind == "shard-internal"
    assert is_shard_internal_plugin("packages.maa_hub")
    assert is_shard_internal_plugin("pallas_plugin_maa_hub")
