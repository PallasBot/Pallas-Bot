from __future__ import annotations

import json

from fastapi import FastAPI
from fastapi.testclient import TestClient

from packages.pb_webui import extended_api as mod
from packages.pb_webui.config import Config


def _build_client(monkeypatch) -> TestClient:
    monkeypatch.setattr(mod, "_check_pallas_write_token", lambda *a, **k: None)
    monkeypatch.setattr(mod, "_require_pallas_token_configured", lambda *a, **k: None)
    monkeypatch.setattr(mod, "ensure_console_metrics_hooks", lambda: None)
    app = FastAPI()
    mod.register_extended_api(app, api_base="/pallas/api", plugin_config=Config())
    return TestClient(app)


def test_plugin_governance_get_returns_commands_and_runtime(monkeypatch) -> None:
    monkeypatch.setattr(
        "pallas.core.plugin_capabilities.build_plugin_capabilities_ui",
        lambda: {
            "plugins": [
                {
                    "plugin": "sing",
                    "title": "牛牛唱歌",
                    "commands": [
                        {
                            "command_id": "sing.play",
                            "label": "牛牛唱歌",
                            "default_level": "everyone",
                            "effective_level": "staff",
                            "default_cd_sec": 3,
                            "effective_cd_sec": 9,
                        }
                    ],
                    "llm_tools": [],
                    "storage_keys": [],
                    "reload_policy": "config_only",
                    "activation_policy": "workers-restart",
                }
            ],
            "levels": [],
        },
    )
    monkeypatch.setattr(
        mod,
        "_list_plugins_dict",
        lambda: [
            {
                "package": "sing",
                "name": "sing",
                "global_disable_protected": True,
                "help_ignored": True,
                "usage": "唱歌",
                "metadata": {
                    "extra": {
                        "menu_data": [
                            {
                                "func": "唱歌",
                                "trigger_condition": "牛牛唱歌 xxx",
                                "trigger_scene": "群内",
                                "brief_des": "唱一首歌。",
                                "command_permission": "sing.play",
                            }
                        ]
                    }
                },
            }
        ],
    )
    monkeypatch.setattr("packages.help.visibility.load_help_hidden_plugins", lambda: ["help", "sing"])
    monkeypatch.setattr("packages.help.global_disable.load_global_disabled_plugins", lambda: ["sing"])

    async def fake_list_blocked(_plugin: str) -> list[int]:
        return [111, 222]

    monkeypatch.setattr(
        "pallas.core.perm.plugin_acl.list_plugin_blocked_user_ids",
        fake_list_blocked,
    )
    monkeypatch.setattr(
        "pallas.core.perm.schema.build_command_perm_ui",
        lambda _overrides: {
            "plugins": [
                {
                    "plugin": "sing",
                    "title": "牛牛唱歌",
                    "commands": [
                        {
                            "command_id": "sing.play",
                            "label": "牛牛唱歌",
                            "default_level": "everyone",
                            "effective_level": "staff",
                        }
                    ],
                }
            ],
            "levels": [],
        },
    )
    monkeypatch.setattr(
        "pallas.core.limits.schema.build_command_limits_ui",
        lambda _overrides: {
            "plugins": [
                {
                    "plugin": "sing",
                    "title": "牛牛唱歌",
                    "commands": [
                        {
                            "command_id": "sing.play",
                            "label": "牛牛唱歌",
                            "default_cd_sec": 3,
                            "effective_cd_sec": 9,
                        }
                    ],
                }
            ]
        },
    )

    client = _build_client(monkeypatch)
    response = client.get("/pallas/api/plugins/sing/governance")

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["ok"] is True
    assert payload["data"]["commands"][0]["command_id"] == "sing.play"
    assert payload["data"]["commands"][0]["trigger_condition"] == "牛牛唱歌 xxx"
    assert payload["data"]["perm_ui_filtered"]["plugins"][0]["commands"][0]["trigger_condition"] == "牛牛唱歌 xxx"
    assert payload["data"]["menu_items"][0]["command_permission"] == "sing.play"
    assert payload["data"]["runtime"]["global_disable"] is True
    assert payload["data"]["runtime"]["help_hidden"] is True
    assert payload["data"]["runtime"]["global_disable_protected"] is True
    assert payload["data"]["runtime"]["help_ignored"] is True
    assert payload["data"]["perm_ui_filtered"]["levels"] == []
    assert payload["data"]["perm_ui_filtered"]["plugins"][0]["commands"][0]["command_id"] == "sing.play"
    assert payload["data"]["limits_ui_filtered"]["plugins"][0]["commands"][0]["command_id"] == "sing.play"
    assert payload["data"]["blocked_user_ids"] == [111, 222]
    assert payload["data"]["activation_policy"] == "workers-restart"


def test_plugin_governance_put_filters_only_plugin_prefix(monkeypatch) -> None:
    saved_env: dict[str, str] = {}
    cleared: dict[str, bool] = {"perm": False, "limits": False}

    def fake_upsert_env(items):
        saved_env.update(items)

    async def fake_invalidate_disabled_plugin_gate_cache(*, clear_all: bool = False) -> None:
        assert clear_all is True

    monkeypatch.setattr("pallas.console.webui.plugin_api.upsert_env_dotenv_items", fake_upsert_env)
    monkeypatch.setattr(
        "pallas.core.perm.config.clear_cmd_perm_cache",
        lambda: cleared.__setitem__("perm", True),
    )
    monkeypatch.setattr(
        "pallas.core.limits.config.clear_command_limits_cache",
        lambda: cleared.__setitem__("limits", True),
    )
    monkeypatch.setattr("packages.help.visibility.load_help_hidden_plugins", list)
    monkeypatch.setattr("packages.help.global_disable.load_global_disabled_plugins", list)
    monkeypatch.setattr(
        "packages.help.visibility.save_help_hidden_plugins",
        lambda hidden: sorted(set(hidden)),
    )
    monkeypatch.setattr(
        "packages.help.global_disable.save_global_disabled_plugins",
        lambda disabled: sorted(set(disabled)),
    )
    monkeypatch.setattr(
        "packages.help.plugin_manager.invalidate_disabled_plugin_gate_cache",
        fake_invalidate_disabled_plugin_gate_cache,
    )
    monkeypatch.setattr(
        "pallas.core.perm.config.get_cmd_perm_config",
        lambda: type("_Cfg", (), {"command_permission_overrides": {}})(),
    )
    monkeypatch.setattr(
        "pallas.core.limits.config.get_command_limits_config",
        lambda: type("_Cfg", (), {"command_limit_overrides": {}})(),
    )
    monkeypatch.setattr(mod, "drop_read_cache", lambda *a, **k: None)

    async def fake_sync_blocked(plugin: str, user_ids: list[int]) -> list[int]:
        assert plugin == "sing"
        assert user_ids == [333]
        return [333]

    monkeypatch.setattr(
        "pallas.core.perm.plugin_acl.sync_plugin_blocked_user_ids",
        fake_sync_blocked,
    )

    client = _build_client(monkeypatch)
    response = client.put(
        "/pallas/api/plugins/sing/governance",
        json={
            "command_permission_overrides": {
                "sing.play": "staff",
                "other_plugin.run": "superuser",
            },
            "command_limit_overrides": {
                "sing.play": 12,
                "other_plugin.run": 99,
            },
            "global_disable": True,
            "help_hidden": True,
            "blocked_user_ids": [333],
        },
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["ok"] is True
    saved_perm = json.loads(saved_env["PALLAS_COMMAND_PERMISSION_OVERRIDES"])
    saved_limit = json.loads(saved_env["PALLAS_COMMAND_LIMIT_OVERRIDES"])
    assert saved_perm == {"sing.play": "staff"}
    assert saved_limit == {"sing.play": 12}
    assert cleared == {"perm": True, "limits": True}
    assert payload["data"]["runtime"]["global_disable"] is True
    assert payload["data"]["runtime"]["help_hidden"] is True
    assert payload["data"]["blocked_user_ids"] == [333]


def test_plugin_governance_put_keeps_existing_overrides_and_honors_alias_prefix(monkeypatch) -> None:
    saved_env: dict[str, str] = {}

    def fake_upsert_env(items):
        saved_env.update(items)

    async def fake_invalidate_disabled_plugin_gate_cache(*, clear_all: bool = False) -> None:
        assert clear_all is True

    monkeypatch.setattr("pallas.console.webui.plugin_api.upsert_env_dotenv_items", fake_upsert_env)
    monkeypatch.setattr("packages.help.visibility.load_help_hidden_plugins", list)
    monkeypatch.setattr("packages.help.global_disable.load_global_disabled_plugins", list)
    monkeypatch.setattr(
        "packages.help.visibility.save_help_hidden_plugins",
        lambda hidden: sorted(set(hidden)),
    )
    monkeypatch.setattr(
        "packages.help.global_disable.save_global_disabled_plugins",
        lambda disabled: sorted(set(disabled)),
    )
    monkeypatch.setattr(
        "packages.help.plugin_manager.invalidate_disabled_plugin_gate_cache",
        fake_invalidate_disabled_plugin_gate_cache,
    )
    monkeypatch.setattr(
        "pallas.core.perm.config.get_cmd_perm_config",
        lambda: type(
            "_Cfg",
            (),
            {"command_permission_overrides": {"help.help": "everyone", "relogin.create": "superuser"}},
        )(),
    )
    monkeypatch.setattr(
        "pallas.core.limits.config.get_command_limits_config",
        lambda: type("_Cfg", (), {"command_limit_overrides": {"help.help": 3}})(),
    )
    monkeypatch.setattr(mod, "drop_read_cache", lambda *a, **k: None)

    async def fake_sync_blocked(_plugin: str, user_ids: list[int]) -> list[int]:
        return user_ids

    monkeypatch.setattr(
        "pallas.core.perm.plugin_acl.sync_plugin_blocked_user_ids",
        fake_sync_blocked,
    )

    client = _build_client(monkeypatch)
    response = client.put(
        "/pallas/api/plugins/relogin_bot/governance",
        json={
            "command_permission_overrides": {
                "relogin.create": "bot_moderator",
                "help.help": "group_moderator",
            },
            "command_limit_overrides": {},
            "global_disable": False,
            "help_hidden": False,
            "blocked_user_ids": [],
        },
    )

    assert response.status_code == 200, response.text
    saved_perm = json.loads(saved_env["PALLAS_COMMAND_PERMISSION_OVERRIDES"])
    assert saved_perm == {
        "help.help": "everyone",
        "relogin.create": "bot_moderator",
    }


def test_plugin_config_get_resolves_official_pip_plugin_short_name(monkeypatch) -> None:
    client = _build_client(monkeypatch)
    response = client.get("/pallas/api/plugins/draw/config")

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["ok"] is True
    assert payload["data"]["module"]
    assert payload["data"]["fields"]


def test_plugin_config_get_preserves_field_groups_in_response_model(monkeypatch) -> None:
    """GET 经 response_model 序列化后须保留 field_groups，否则前端会退回单组面板。"""
    monkeypatch.setattr(
        mod,
        "plugin_config_payload",
        lambda _name: {
            "plugin": "pb_core",
            "module": "pb_core.config",
            "fields": [{"name": "enabled", "type": "bool", "value": True}],
            "unexpected_keys": [],
            "field_groups": [
                {"id": "core", "title": "核心", "field_names": ["enabled"]},
                {"id": "mail", "title": "邮件", "field_names": ["smtp_user"]},
            ],
            "hot_reload": True,
        },
    )
    client = _build_client(monkeypatch)
    response = client.get("/pallas/api/plugins/pb_core/config")

    assert response.status_code == 200, response.text
    data = response.json()["data"]
    groups = data.get("field_groups") or []
    assert len(groups) == 2
    assert groups[0]["id"] == "core"
    assert data.get("hot_reload") is True
