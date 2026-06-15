from nonebot.plugin import PluginMetadata

from src.features.command_limits.metadata import command_limits_from_metadata


def _import_command_limit_plugins() -> None:
    import src.plugins.bot_status  # noqa: F401
    import src.plugins.connectivity  # noqa: F401
    import src.plugins.help  # noqa: F401


def _patch_loaded_plugins(monkeypatch):
    from types import SimpleNamespace

    from src.plugins.bot_status import __plugin_meta__ as bot_status_meta
    from src.plugins.connectivity import __plugin_meta__ as connectivity_meta
    from src.plugins.help import __plugin_meta__ as help_meta

    plugins = [
        SimpleNamespace(name="bot_status", metadata=bot_status_meta),
        SimpleNamespace(name="connectivity", metadata=connectivity_meta),
        SimpleNamespace(name="help", metadata=help_meta),
    ]
    monkeypatch.setattr("src.features.command_limits.schema.get_loaded_plugins", lambda: plugins)


def test_command_limits_from_metadata():
    meta = PluginMetadata(
        name="t",
        description="t。",
        usage="",
        extra={
            "command_limits": [
                {"id": "t.demo", "cd": 5},
                {"id": "bad", "cd_sec": 0},
            ],
        },
    )
    limits = command_limits_from_metadata(meta)
    assert len(limits) == 2
    assert limits[0].id == "t.demo"
    assert limits[0].cd_sec == 5
    assert limits[1].id == "bad"
    assert limits[1].cd_sec == 0


def test_command_limit_action_key():
    from src.features.command_limits import command_limit_action_key

    assert command_limit_action_key("my_plugin.demo") == "cmd_limit:my_plugin.demo"


def test_existing_plugin_metadata_declares_command_limits():
    from src.plugins.bot_status import __plugin_meta__ as bot_status_meta
    from src.plugins.connectivity import __plugin_meta__ as connectivity_meta
    from src.plugins.help import __plugin_meta__ as help_meta

    assert [item.id for item in command_limits_from_metadata(bot_status_meta)] == [
        "bot_status.status",
        "bot_status.count",
    ]
    assert [item.id for item in command_limits_from_metadata(connectivity_meta)] == ["connectivity.probe"]
    assert [item.id for item in command_limits_from_metadata(help_meta)] == ["help.help"]


def test_command_limits_ui_groups_existing_plugins(monkeypatch):
    from src.features.command_limits.schema import build_command_limits_ui

    _import_command_limit_plugins()
    _patch_loaded_plugins(monkeypatch)
    ui = build_command_limits_ui({})
    commands = {row["id"]: row for row in ui["commands"]}

    assert commands["help.help"]["default_cd_sec"] == 3
    assert commands["help.help"]["effective_cd_sec"] == 3
    assert commands["help.help"]["plugin"] == "help"
    assert commands["bot_status.status"]["plugin"] == "bot_status"
    assert commands["connectivity.probe"]["plugin"] == "connectivity"


def test_command_limits_ui_uses_override_values(monkeypatch):
    from src.features.command_limits.schema import build_command_limits_ui

    _import_command_limit_plugins()
    _patch_loaded_plugins(monkeypatch)
    ui = build_command_limits_ui({"help.help": 9})
    commands = {row["id"]: row for row in ui["commands"]}
    assert commands["help.help"]["effective_cd_sec"] == 9


def test_effective_command_limit_prefers_override(monkeypatch):
    from src.features.command_limits.schema import effective_command_limit_for

    _import_command_limit_plugins()
    _patch_loaded_plugins(monkeypatch)
    assert effective_command_limit_for("help.help", {"help.help": 7}) == 7
    assert effective_command_limit_for("help.help", {}) == 3


def test_get_command_cooldown_sec_reads_config_override(monkeypatch):
    from src.features.command_limits.cooldown import get_command_cooldown_sec

    class DummyCfg:
        command_limit_overrides = {"help.help": 12}

    _import_command_limit_plugins()
    _patch_loaded_plugins(monkeypatch)
    monkeypatch.setattr("src.features.command_limits.cooldown.get_command_limits_config", lambda: DummyCfg())
    assert get_command_cooldown_sec("help.help") == 12


def test_zero_command_cooldown_disables_limit(monkeypatch):
    from src.features.command_limits.cooldown import get_command_cooldown_sec

    class DummyCfg:
        command_limit_overrides = {"help.help": 0}

    _import_command_limit_plugins()
    _patch_loaded_plugins(monkeypatch)
    monkeypatch.setattr("src.features.command_limits.cooldown.get_command_limits_config", lambda: DummyCfg())
    assert get_command_cooldown_sec("help.help") == 0
