import importlib
from unittest.mock import patch

from nonebot.plugin import PluginMetadata

from src.features.plugin_reload.l2 import (
    reload_metadata_after_plugin_config_save,
    reload_plugin_metadata_l2,
)


def test_reload_plugin_metadata_l2_clears_caches():
    ingress_mod = importlib.import_module("src.platform.ingress.plugin_command_plaintext")
    storage_mod = importlib.import_module("src.features.plugin_storage.schema")
    cmd_perm_mod = importlib.import_module("src.features.cmd_perm.schema")
    help_mod = importlib.import_module("src.plugins.help.plugin_manager")

    with (
        patch.object(ingress_mod, "clear_plugin_command_plaintext_cache") as ingress,
        patch.object(storage_mod, "clear_plugin_storage_registry_cache") as storage,
        patch.object(cmd_perm_mod, "clear_merged_defaults_cache") as cmd_perm,
        patch.object(help_mod, "clear_help_cache") as help_cache,
    ):
        reload_plugin_metadata_l2()
    ingress.assert_called_once()
    storage.assert_called_once()
    cmd_perm.assert_called_once()
    help_cache.assert_called_once()


def test_reload_metadata_after_plugin_config_save_skips_config_only():
    with patch("src.features.plugin_reload.l2.reload_plugin_metadata_l2") as l2:
        assert reload_metadata_after_plugin_config_save("missing_plugin") is False
    l2.assert_not_called()


def test_reload_metadata_after_plugin_config_save_runs_for_metadata_policy():
    meta = PluginMetadata(name="t", description="t。", usage="", extra={"reload_policy": "metadata"})

    class FakePlugin:
        name = "help"
        metadata = meta

    with (
        patch("src.features.plugin_reload.l2.get_loaded_plugins", return_value=[FakePlugin()]),
        patch("src.features.plugin_reload.l2.reload_plugin_metadata_l2") as l2,
    ):
        assert reload_metadata_after_plugin_config_save("help") is True
    l2.assert_called_once()
