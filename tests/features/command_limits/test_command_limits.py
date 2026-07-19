from nonebot.plugin import PluginMetadata

from pallas.core.limits.metadata import command_limits_from_metadata


def _plugin_meta(name: str, command_ids: list[str]) -> PluginMetadata:
    return PluginMetadata(
        name=name,
        description=f"{name} test plugin。",
        usage="",
        extra={
            "command_limits": [{"id": cid, "cd_sec": 3} for cid in command_ids],
        },
    )


def _bot_status_meta() -> PluginMetadata:
    return _plugin_meta(
        "bot_status",
        [
            "bot_status.status",
            "bot_status.count",
            "bot_status.test_mail",
            "bot_status.offline_mail",
        ],
    )


def _import_command_limit_plugins() -> None:
    import packages.help  # noqa: F401
    import pallas.product.service_gateways.connectivity  # noqa: F401


def _patch_loaded_plugins(monkeypatch):
    from types import SimpleNamespace

    from packages.help import __plugin_meta__ as help_meta
    from pallas.core.limits.schema import clear_merged_command_limits_cache
    from pallas.product.service_gateways.connectivity import __plugin_meta__ as connectivity_meta

    bot_status_meta = _bot_status_meta()
    maa_meta = _plugin_meta(
        "maa",
        ["maa.status", "maa.clear_queue", "maa.switch_device", "maa.raw_task", "maa.control"],
    )
    sing_meta = _plugin_meta(
        "sing",
        ["sing.sing", "sing.play", "sing.request_song", "sing.song_title"],
    )

    clear_merged_command_limits_cache()

    plugins = [
        SimpleNamespace(name="bot_status", metadata=bot_status_meta),
        SimpleNamespace(name="connectivity", metadata=connectivity_meta),
        SimpleNamespace(name="help", metadata=help_meta),
        SimpleNamespace(name="maa", metadata=maa_meta),
        SimpleNamespace(name="sing", metadata=sing_meta),
    ]
    monkeypatch.setattr("pallas.core.limits.schema.get_loaded_plugins", lambda: plugins)


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
    from pallas.core.limits import command_limit_action_key

    assert command_limit_action_key("my_plugin.demo") == "cmd_limit:my_plugin.demo"


def test_existing_plugin_metadata_declares_command_limits():
    from packages.help import __plugin_meta__ as help_meta
    from pallas.product.service_gateways.connectivity import __plugin_meta__ as connectivity_meta

    bot_status_meta = _bot_status_meta()
    maa_meta = _plugin_meta(
        "maa",
        ["maa.status", "maa.clear_queue", "maa.switch_device", "maa.raw_task", "maa.control"],
    )
    sing_meta = _plugin_meta(
        "sing",
        ["sing.sing", "sing.play", "sing.request_song", "sing.song_title"],
    )

    assert [item.id for item in command_limits_from_metadata(bot_status_meta)] == [
        "bot_status.status",
        "bot_status.count",
        "bot_status.test_mail",
        "bot_status.offline_mail",
    ]
    assert [item.id for item in command_limits_from_metadata(connectivity_meta)] == ["connectivity.probe"]
    assert [item.id for item in command_limits_from_metadata(help_meta)] == [
        "help.help",
        "help.plugin_enable",
        "help.plugin_disable",
        "help.plugin_enable_all",
        "help.plugin_disable_all",
    ]
    assert [item.id for item in command_limits_from_metadata(sing_meta)] == [
        "sing.sing",
        "sing.play",
        "sing.request_song",
        "sing.song_title",
    ]
    assert [item.id for item in command_limits_from_metadata(maa_meta)] == [
        "maa.status",
        "maa.clear_queue",
        "maa.switch_device",
        "maa.raw_task",
        "maa.control",
    ]


def test_command_limits_ui_groups_existing_plugins(monkeypatch):
    from pallas.core.limits.schema import build_command_limits_ui

    _import_command_limit_plugins()
    _patch_loaded_plugins(monkeypatch)
    ui = build_command_limits_ui({})
    commands = {row["id"]: row for row in ui["commands"]}

    assert commands["help.help"]["default_cd_sec"] == 3
    assert commands["help.help"]["effective_cd_sec"] == 3
    assert commands["help.help"]["plugin"] == "help"
    assert commands["bot_status.status"]["plugin"] == "bot_status"
    assert commands["connectivity.probe"]["plugin"] == "connectivity"
    assert commands["sing.sing"]["plugin"] == "sing"
    assert commands["maa.control"]["plugin"] == "maa"


def test_command_limits_ui_label_prefers_chinese_name(monkeypatch):
    from types import SimpleNamespace

    from pallas.core.limits.schema import build_command_limits_ui, clear_merged_command_limits_cache

    clear_merged_command_limits_cache()
    maa_meta = _plugin_meta("maa", ["maa.control", "maa.status", "maa.unknown_cmd"])
    monkeypatch.setattr(
        "pallas.core.limits.schema.get_loaded_plugins",
        lambda: [SimpleNamespace(name="maa", metadata=maa_meta)],
    )
    monkeypatch.setattr(
        "pallas.core.commands.metadata_stub.iter_plugin_init_paths_for_disk_scan",
        list,
    )
    # command_permissions 声明的 label 优先于集中映射
    monkeypatch.setattr(
        "pallas.core.perm.schema.command_labels_from_permissions",
        lambda: {"maa.status": "牛牛MAA状态（声明）"},
    )

    ui = build_command_limits_ui({})
    commands = {row["id"]: row for row in ui["commands"]}
    # 1) 优先用 command_permissions 声明 label
    assert commands["maa.status"]["label"] == "牛牛MAA状态（声明）"
    # 2) 无声明 label 时回退到集中映射的中文名
    assert commands["maa.control"]["label"] == "MAA 远控指令"
    # 3) 既无声明也无映射时回退为裸命令 id
    assert commands["maa.unknown_cmd"]["label"] == "maa.unknown_cmd"


def test_command_limits_ui_uses_override_values(monkeypatch):
    from pallas.core.limits.schema import build_command_limits_ui

    _import_command_limit_plugins()
    _patch_loaded_plugins(monkeypatch)
    ui = build_command_limits_ui({"help.help": 9})
    commands = {row["id"]: row for row in ui["commands"]}
    assert commands["help.help"]["effective_cd_sec"] == 9


def test_command_limits_ui_includes_worker_plugins_from_disk_when_hub_loaded_plugins_are_partial(monkeypatch):
    from pathlib import Path
    from types import SimpleNamespace

    from packages.help import __plugin_meta__ as help_meta
    from pallas.core.limits.schema import build_command_limits_ui, clear_merged_command_limits_cache

    clear_merged_command_limits_cache()
    monkeypatch.setattr(
        "pallas.core.limits.schema.get_loaded_plugins",
        lambda: [SimpleNamespace(name="help", metadata=help_meta)],
    )
    monkeypatch.setattr(
        "pallas.core.commands.metadata_stub.iter_plugin_init_paths_for_disk_scan",
        lambda: [
            ("maa", Path("packages/maa/__init__.py")),
            ("sing", Path("packages/sing/__init__.py")),
        ],
    )
    monkeypatch.setattr(
        "pallas.core.limits.schema.parse_command_limits_stub",
        lambda path: (
            {
                "name": path.parent.name,
                "command_limits": command_limits_from_metadata(
                    _plugin_meta(
                        path.parent.name,
                        {
                            "maa": [
                                "maa.status",
                                "maa.clear_queue",
                                "maa.switch_device",
                                "maa.raw_task",
                                "maa.control",
                            ],
                            "sing": ["sing.sing", "sing.play", "sing.request_song", "sing.song_title"],
                        }.get(path.parent.name, []),
                    )
                ),
            }
            if path.parent.name in {"maa", "sing"}
            else None
        ),
    )
    monkeypatch.setattr(
        Path,
        "is_file",
        lambda self: self.name == "__init__.py" and self.parent.name in {"help", "maa", "sing"},
    )
    ui = build_command_limits_ui({})
    commands = {row["id"]: row for row in ui["commands"]}

    assert "help.help" in commands
    assert "sing.sing" in commands
    assert "maa.control" in commands


def test_effective_command_limit_prefers_override(monkeypatch):
    from pallas.core.limits.schema import effective_command_limit_for

    _import_command_limit_plugins()
    _patch_loaded_plugins(monkeypatch)
    assert effective_command_limit_for("help.help", {"help.help": 7}) == 7
    assert effective_command_limit_for("help.help", {}) == 3


def test_get_command_cooldown_sec_reads_config_override(monkeypatch):
    from pallas.core.limits.cooldown import get_command_cooldown_sec

    class DummyCfg:
        command_limit_overrides = {"help.help": 12}

    _import_command_limit_plugins()
    _patch_loaded_plugins(monkeypatch)
    monkeypatch.setattr("pallas.core.limits.cooldown.get_command_limits_config", lambda: DummyCfg())
    assert get_command_cooldown_sec("help.help") == 12


def test_zero_command_cooldown_disables_limit(monkeypatch):
    from pallas.core.limits.cooldown import get_command_cooldown_sec

    class DummyCfg:
        command_limit_overrides = {"help.help": 0}

    _import_command_limit_plugins()
    _patch_loaded_plugins(monkeypatch)
    monkeypatch.setattr("pallas.core.limits.cooldown.get_command_limits_config", lambda: DummyCfg())
    assert get_command_cooldown_sec("help.help") == 0


def test_effective_command_cooldown_text(monkeypatch):
    from pallas.core.limits.menu_display import effective_command_cooldown_text

    _import_command_limit_plugins()
    _patch_loaded_plugins(monkeypatch)

    assert effective_command_cooldown_text({"command_permission": "help.help"}) == "冷却 3 秒"
    assert (
        effective_command_cooldown_text({"command_permissions": ["help.plugin_enable", "help.plugin_disable"]})
        == "冷却 5 秒"
    )
    assert effective_command_cooldown_text({}) == ""
    assert effective_command_cooldown_text({"command_permission": "unknown.cmd"}) == ""


def test_effective_command_cooldown_text_respects_override(monkeypatch):
    from pallas.core.limits.menu_display import effective_command_cooldown_text

    class DummyCfg:
        command_limit_overrides = {"help.help": 9}

    _import_command_limit_plugins()
    _patch_loaded_plugins(monkeypatch)
    monkeypatch.setattr("pallas.core.limits.menu_display.get_command_limits_config", lambda: DummyCfg())
    assert effective_command_cooldown_text({"command_permission": "help.help"}) == "冷却 9 秒"


def test_effective_command_cooldown_text_zero(monkeypatch):
    from pallas.core.limits.menu_display import effective_command_cooldown_text

    class DummyCfg:
        command_limit_overrides = {"help.help": 0}

    _import_command_limit_plugins()
    _patch_loaded_plugins(monkeypatch)
    monkeypatch.setattr("pallas.core.limits.menu_display.get_command_limits_config", lambda: DummyCfg())
    assert effective_command_cooldown_text({"command_permission": "help.help"}) == "无冷却"
