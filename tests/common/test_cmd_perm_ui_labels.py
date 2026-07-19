from pallas.core.perm.schema import build_command_perm_ui


def test_command_perm_ui_labels_without_plugins():
    ui = build_command_perm_ui({})
    for pg in ui["plugins"]:
        assert pg["title"] == pg["title"].strip()
        assert pg["title"] != pg["plugin"] or pg["plugin"] == "maa"
        for cmd in pg["commands"]:
            assert cmd["label"] != cmd["command_id"], f"missing label: {cmd['command_id']}"
            assert "…" not in cmd["label"]
    draw = next(pg for pg in ui["plugins"] if pg["plugin"] == "draw")
    labels = {c["command_id"]: c["label"] for c in draw["commands"]}
    assert "draw.gateway" not in labels
    assert labels["draw.draw"] == "牛牛画画"


def test_command_perm_ui_level_labels_chinese():
    ui = build_command_perm_ui({})
    assert [lv["label"] for lv in ui["levels"]] == [
        "所有人",
        "号主",
        "群管/群主",
        "群管或号主",
        "仅超管",
    ]


def test_command_perm_ui_includes_trigger_condition_from_menu(monkeypatch) -> None:
    from types import SimpleNamespace

    from packages.help import __plugin_meta__ as help_meta
    from pallas.core.perm.schema import build_command_perm_ui, clear_merged_defaults_cache

    clear_merged_defaults_cache()
    plugins = [SimpleNamespace(name="help", metadata=help_meta)]
    monkeypatch.setattr("pallas.core.perm.schema.get_loaded_plugins", lambda: plugins)
    monkeypatch.setattr("nonebot.get_loaded_plugins", lambda: plugins)
    monkeypatch.setattr(
        "pallas.core.commands.metadata_stub.iter_plugin_init_paths_for_disk_scan",
        list,
    )

    ui = build_command_perm_ui({})
    by_plugin = {row["plugin"]: row for row in ui["plugins"]}
    commands = {cmd["command_id"]: cmd for cmd in by_plugin["help"]["commands"]}
    assert "牛牛帮助" in commands["help.help"]["trigger_condition"]


def test_command_perm_ui_includes_worker_plugins_from_disk_when_hub_loaded_plugins_are_partial(monkeypatch):
    from pathlib import Path
    from types import SimpleNamespace

    from nonebot.plugin import PluginMetadata

    from pallas.core.perm.metadata import CommandPermissionDecl
    from pallas.core.perm.schema import build_command_perm_ui, clear_merged_defaults_cache

    def _plugin_meta(name: str, command_ids: list[str]) -> PluginMetadata:
        return PluginMetadata(
            name=name,
            description=f"{name} test plugin。",
            usage="",
            extra={
                "command_permissions": [{"id": cid, "label": cid, "default": "everyone"} for cid in command_ids],
            },
        )

    import packages.help

    clear_merged_defaults_cache()
    monkeypatch.setattr(
        "pallas.core.perm.schema.get_loaded_plugins",
        lambda: [SimpleNamespace(name="help", metadata=packages.help.__plugin_meta__)],
    )
    monkeypatch.setattr(
        "pallas.core.commands.metadata_stub.iter_plugin_init_paths_for_disk_scan",
        lambda: [
            ("sing", Path("packages/sing/__init__.py")),
            ("chat", Path("packages/chat/__init__.py")),
        ],
    )
    monkeypatch.setattr(
        "pallas.core.perm.schema.parse_command_permissions_stub",
        lambda path: (
            {
                "name": path.parent.name,
                "command_permissions": [
                    CommandPermissionDecl(id=cid, label=cid, default="everyone")
                    for cid in {
                        "sing": ["sing.sing", "sing.play"],
                        "chat": ["chat.chat"],
                    }.get(path.parent.name, [])
                ],
            }
            if path.parent.name in {"sing", "chat"}
            else None
        ),
    )
    monkeypatch.setattr(
        Path,
        "is_file",
        lambda self: self.name == "__init__.py" and self.parent.name in {"help", "sing", "chat"},
    )

    ui = build_command_perm_ui({})
    by_plugin = {row["plugin"]: row for row in ui["plugins"]}

    assert "help" in by_plugin
    assert "sing" in by_plugin
    assert "chat" in by_plugin
    assert {cmd["command_id"] for cmd in by_plugin["sing"]["commands"]} >= {"sing.sing", "sing.play"}
    assert {cmd["command_id"] for cmd in by_plugin["chat"]["commands"]} >= {"chat.chat"}
