from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from pallas.core.plugin_capabilities.schema import build_plugin_capabilities_ui
from pallas.core.storage.declare import plugin_storage_row
from pallas.core.storage.deploy_store import DeployPluginStorage, deploy_storage_path
from pallas.core.storage.schema import clear_plugin_storage_registry_cache


@pytest.fixture(autouse=True)
def reset_storage_registry() -> None:
    clear_plugin_storage_registry_cache()
    yield
    clear_plugin_storage_registry_cache()


def test_deploy_storage_roundtrip(tmp_path, monkeypatch) -> None:
    class FakePlugin:
        name = "help"
        metadata = SimpleNamespace(
            name="牛牛帮助",
            extra={
                "plugin_storage": [
                    plugin_storage_row("hidden_plugins", scope="deploy"),
                ]
            },
        )

    monkeypatch.setattr("nonebot.get_loaded_plugins", lambda: [FakePlugin()])
    monkeypatch.setattr(
        "pallas.core.storage.deploy_store.plugin_data_dir",
        lambda _name: tmp_path / "help",
    )
    clear_plugin_storage_registry_cache()

    store = DeployPluginStorage("help")
    store.set("hidden_plugins", ["demo"])
    assert store.get("hidden_plugins") == ["demo"]
    path = deploy_storage_path("help")
    assert path.is_file()
    raw = json.loads(path.read_text(encoding="utf-8"))
    assert raw["hidden_plugins"] == ["demo"]


def test_build_plugin_capabilities_ui_groups(monkeypatch) -> None:
    class FakeDraw:
        name = "draw"
        metadata = SimpleNamespace(
            name="牛牛画画",
            extra={
                "command_permissions": [{"id": "draw.draw", "label": "牛牛画画", "default": "everyone"}],
                "command_limits": [{"id": "draw.draw", "cd_sec": 3}],
                "llm_tools": [
                    {
                        "name": "draw.image",
                        "command_id": "draw.draw",
                        "description": "生图",
                        "parameters": {"type": "object", "properties": {}},
                        "command_template": "牛牛画画 {prompt}",
                        "default": True,
                    }
                ],
                "plugin_storage": [
                    plugin_storage_row("daily_usage", scope="deploy", label="日用量"),
                ],
            },
        )

    monkeypatch.setattr("nonebot.get_loaded_plugins", lambda: [FakeDraw()])
    monkeypatch.setattr("pallas.core.perm.schema.get_loaded_plugins", lambda: [FakeDraw()])
    limit_row = type("Row", (), {"id": "draw.draw", "cd_sec": 3})()
    monkeypatch.setattr(
        "pallas.core.limits.schema._all_command_limit_rows",
        lambda: [("draw", "牛牛画画", [limit_row])],
    )
    clear_plugin_storage_registry_cache()

    ui = build_plugin_capabilities_ui()
    draw = next(row for row in ui["plugins"] if row["plugin"] == "draw")
    assert draw["commands"][0]["command_id"] == "draw.draw"
    assert draw["commands"][0]["effective_cd_sec"] == 3
    assert draw["llm_tools"][0]["name"] == "draw.image"
    assert draw["storage_keys"][0]["key"] == "daily_usage"
    assert draw.get("reload_policy") in (None, "config_only")
    assert draw.get("activation_policy") == "hot-reloadable"
