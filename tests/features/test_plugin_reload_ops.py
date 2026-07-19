from __future__ import annotations

from types import ModuleType
from unittest.mock import patch

from nonebot.plugin import PluginMetadata

from pallas.console.cli.commands import plugin_cmd
from pallas.core.plugin_reload.reload_ops import execute_plugin_reload


def test_execute_plugin_reload_config_only_hint():
    with patch(
        "pallas.core.plugin_reload.reload_ops.reload_policy_for_plugin_name",
        return_value="config_only",
    ):
        result = execute_plugin_reload("help")
    assert result["ok"] is True
    assert result["action"] == "config-only-hint"
    assert "config_only" in result["message"]


def test_execute_plugin_reload_metadata_when_loaded():
    meta = PluginMetadata(name="t", description="t。", usage="", extra={"reload_policy": "metadata"})

    class FakePlugin:
        name = "help"
        metadata = meta
        module = ModuleType("packages.help")
        module.__name__ = "packages.help"

    with (
        patch(
            "pallas.core.plugin_reload.reload_ops.reload_policy_for_plugin_name",
            return_value="metadata",
        ),
        patch(
            "pallas.core.plugin_reload.reload_ops.loaded_plugin_module_prefix",
            return_value="packages.help",
        ),
        patch("pallas.core.plugin_reload.reload_ops.reload_plugin_metadata_index") as reload_index,
    ):
        result = execute_plugin_reload("help")
    assert result["ok"] is True
    assert result["action"] == "metadata-reload"
    reload_index.assert_called_once()


def test_execute_plugin_reload_not_loaded():
    with (
        patch(
            "pallas.core.plugin_reload.reload_ops.reload_policy_for_plugin_name",
            return_value="metadata",
        ),
        patch(
            "pallas.core.plugin_reload.reload_ops.loaded_plugin_module_prefix",
            return_value=None,
        ),
    ):
        result = execute_plugin_reload("missing")
    assert result["ok"] is False
    assert "未加载" in result["message"]


def test_execute_plugin_reload_full_policy_module_failure():
    with (
        patch(
            "pallas.core.plugin_reload.reload_ops.reload_policy_for_plugin_name",
            return_value="full",
        ),
        patch(
            "pallas.core.plugin_reload.reload_ops.loaded_plugin_module_prefix",
            return_value="packages.help",
        ),
        patch("pallas.core.plugin_reload.reload_ops.reload_plugin_metadata_index"),
        patch(
            "pallas.core.plugin_reload.reload_ops.try_reload_plugin_module",
            return_value=False,
        ),
    ):
        result = execute_plugin_reload("help")
    assert result["ok"] is False
    assert result["action"] == "metadata-only"
    assert "重启" in result["message"]


def test_plugin_cmd_reload_prints_message(capsys):
    with patch(
        "pallas.console.cli.commands.plugin_cmd.execute_plugin_reload",
        return_value={"ok": True, "message": "done"},
    ):
        code = plugin_cmd.run_reload(type("Args", (), {"name": "help"})())
    assert code == 0
    assert "done" in capsys.readouterr().out


def test_plugin_cmd_reload_nonzero_on_failure(capsys):
    with patch(
        "pallas.console.cli.commands.plugin_cmd.execute_plugin_reload",
        return_value={"ok": False, "message": "fail"},
    ):
        code = plugin_cmd.run_reload(type("Args", (), {"name": "help"})())
    assert code == 1
