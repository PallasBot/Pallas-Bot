import importlib
from unittest.mock import patch

from nonebot.plugin import PluginMetadata

from pallas.core.plugin_reload.metadata_index import (
    reload_metadata_after_plugin_config_save,
    reload_plugin_metadata_index,
    reload_policy_for_plugin_name,
)


def test_reload_plugin_metadata_index_clears_caches():
    ingress_mod = importlib.import_module("pallas.core.platform.ingress.plugin_command_plaintext")
    storage_mod = importlib.import_module("pallas.core.storage.schema")
    cmd_perm_mod = importlib.import_module("pallas.core.perm.schema")
    help_mod = importlib.import_module("packages.help.plugin_manager")

    with (
        patch.object(ingress_mod, "clear_plugin_command_plaintext_cache") as ingress,
        patch.object(storage_mod, "clear_plugin_storage_registry_cache") as storage,
        patch.object(cmd_perm_mod, "clear_merged_defaults_cache") as cmd_perm,
        patch.object(help_mod, "clear_help_cache") as help_cache,
    ):
        reload_plugin_metadata_index()
    ingress.assert_called_once()
    storage.assert_called_once()
    cmd_perm.assert_called_once()
    help_cache.assert_called_once()


def test_reload_metadata_after_plugin_config_save_skips_config_only():
    with patch("pallas.product.plugin_reload.metadata_index.reload_plugin_metadata_index") as reload_index:
        assert reload_metadata_after_plugin_config_save("missing_plugin") is False
    reload_index.assert_not_called()


def test_reload_metadata_after_plugin_config_save_runs_for_metadata_policy():
    meta = PluginMetadata(name="t", description="t。", usage="", extra={"reload_policy": "metadata"})

    class FakePlugin:
        name = "help"
        metadata = meta

    with (
        patch("pallas.product.plugin_reload.metadata_index.get_loaded_plugins", return_value=[FakePlugin()]),
        patch("pallas.product.plugin_reload.metadata_index.reload_plugin_metadata_index") as reload_index,
    ):
        assert reload_metadata_after_plugin_config_save("help") is True
    reload_index.assert_called_once()


def test_reload_policy_for_plugin_name_resolves_legacy_alias():
    meta = PluginMetadata(name="t", description="t。", usage="", extra={"reload_policy": "metadata"})

    class FakePlugin:
        name = "pb_webui"
        metadata = meta

    with patch("pallas.product.plugin_reload.metadata_index.get_loaded_plugins", return_value=[FakePlugin()]):
        assert reload_policy_for_plugin_name("pallas_webui") == "metadata"
