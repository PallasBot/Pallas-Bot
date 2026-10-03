from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError

from packages.pb_webui.config import Config
from packages.pb_webui.console_openapi_models import PluginConfigData, PluginGovernanceData
from tools.export_pb_webui_openapi import export_console_openapi


def _resolve_schema(spec: dict[str, Any], schema: dict[str, Any]) -> dict[str, Any]:
    while "$ref" in schema:
        name = schema["$ref"].rsplit("/", 1)[-1]
        schema = spec["components"]["schemas"][name]
    return schema


def _response_data_schema(spec: dict[str, Any], path: str, method: str) -> dict[str, Any]:
    schema = spec["paths"][path][method.lower()]["responses"]["200"]["content"]["application/json"]["schema"]
    envelope = _resolve_schema(spec, schema)
    assert "properties" in envelope, f"{method.upper()} {path} 200 响应缺少对象 envelope schema"
    assert "data" in envelope["properties"], f"{method.upper()} {path} 200 响应缺少 data schema"
    return _resolve_schema(spec, envelope["properties"]["data"])


def _plugin_row_producer_fixture(monkeypatch) -> dict[str, Any]:
    from pallas.console.webui import plugin_catalog

    plugin = SimpleNamespace(
        name="fixture",
        module=SimpleNamespace(__name__="fixture"),
        metadata=SimpleNamespace(name=None, description="", usage="", extra=["future"], type="extension"),
    )
    monkeypatch.setattr(plugin_catalog, "_loaded_plugin_index", lambda: ({}, {"fixture": plugin}))
    monkeypatch.setattr(plugin_catalog, "discover_plugin_packages", list)
    monkeypatch.setattr(plugin_catalog, "discover_extra_plugin_packages", dict)
    monkeypatch.setattr(plugin_catalog, "discover_pyproject_plugin_modules", lambda: ["fixture"])
    monkeypatch.setattr(plugin_catalog, "EXTRA_PACKAGE_MODULES", {})
    monkeypatch.setattr(plugin_catalog, "module_has_config_module", lambda _module: False)
    monkeypatch.setattr(plugin_catalog, "infer_plugin_source", lambda *_a, **_kw: ("core", None))
    monkeypatch.setattr(plugin_catalog, "catalog_plugin_source", lambda _pid, source, **_kw: source)
    monkeypatch.setattr(plugin_catalog, "plugin_version", lambda *_a, **_kw: None)
    monkeypatch.setattr(
        plugin_catalog,
        "resolve_catalog_visuals",
        lambda **_kw: {"avatar": None, "icon": None, "cover": None},
    )
    monkeypatch.setattr(
        plugin_catalog,
        "plugin_uninstall_info",
        lambda **_kw: {"uninstallable": False, "uninstall_kind": None, "uninstall_target": None},
    )
    monkeypatch.setattr(plugin_catalog, "resolve_catalog_process_role", lambda: "unified")
    monkeypatch.setattr(plugin_catalog, "expected_loaded_in_catalog_process", lambda *_a: True)
    monkeypatch.setattr("nonebot.get_loaded_plugins", lambda: [plugin])

    rows = plugin_catalog.build_plugin_catalog_rows()
    assert len(rows) == 1
    return rows[0]


def _instances_producer_fixture(monkeypatch):
    from packages.pb_webui import social_api, system_home_api
    from packages.pb_webui.instances_configs_api import _instances_payload
    from pallas.core.foundation.db import pallas_console_data
    from pallas.core.platform.bot_runtime import plugin_matrix

    db_config = {
        "account": 42,
        "admins": [],
        "auto_accept_friend": False,
        "auto_accept_group": False,
        "security": False,
        "taken_name": {},
        "drunk": {},
        "disabled_plugins": [],
        "community_roster_show_qq": True,
        "persona": None,
        "account_profile_effective": {
            "energy": 0.0,
            "warmth": 0.0,
            "mischief": 0.0,
            "restraint": 0.0,
            "source": "derived",
        },
        "group_style_enabled": True,
    }

    async def list_configs():
        return [db_config]

    async def profiles(*, ensure_accounts: list[int]):
        assert ensure_accounts == [42]
        return {"42": {"nickname": "test", "user_id": 42, "future_profile_value": [1, None]}}

    monkeypatch.setattr(pallas_console_data, "list_all_bot_configs_public", list_configs)
    monkeypatch.setattr(pallas_console_data, "pallas_protocol_snapshot", lambda: None)
    monkeypatch.setattr(system_home_api, "_list_bots_dict", lambda: [{
        "connection_key": "onebot:42",
        "self_id": "42",
        "adapter": "OneBot V11",
        "connected_at_unix": None,
        "ws_port": None,
    }])
    monkeypatch.setattr(plugin_matrix, "protocol_extension_status", lambda: {
        "installed": False,
        "package": "pallas-plugin-protocol",
        "uv_extra": None,
        "install_cli": None,
        "activation_policy": None,
        "repository_url": None,
        "future_status": {"available": True},
    })
    monkeypatch.setattr(social_api, "_collect_online_bot_profiles", profiles)
    return asyncio.run(_instances_payload())


def test_fifth_batch_selected_openapi_responses_are_concrete() -> None:
    spec = export_console_openapi(api_base="/pallas/api")
    paths = spec["paths"]

    plugins_data = _response_data_schema(spec, "/pallas/api/plugins", "get")
    assert plugins_data["type"] == "array"
    assert "$ref" in plugins_data["items"]
    plugin_row = _resolve_schema(spec, plugins_data["items"])
    assert {"name", "module", "metadata", "uninstall_kind", "uninstall_target"} <= set(plugin_row["properties"])

    instances_data = _response_data_schema(spec, "/pallas/api/instances", "get")
    assert {"nonebot_bots", "db_bot_configs", "pallas_protocol", "protocol_extension", "bot_profiles"} <= set(
        instances_data["properties"],
    )

    governance_path = "/pallas/api/plugins/{plugin_name}/governance"
    governance_get = _response_data_schema(spec, governance_path, "get")
    governance_put = _response_data_schema(spec, governance_path, "put")
    assert governance_get["properties"].keys() >= {
        "commands",
        "menu_items",
        "runtime",
        "perm_ui_filtered",
        "limits_ui_filtered",
    }
    assert governance_put["properties"].keys() >= {
        "plugin",
        "command_permission_overrides",
        "command_limit_overrides",
        "blocked_user_ids",
        "runtime",
    }
    assert governance_put != governance_get

    config_path = "/pallas/api/common-config/{section_id}"
    common_get = _response_data_schema(spec, config_path, "get")
    common_put = _response_data_schema(spec, config_path, "put")
    fields = _resolve_schema(spec, common_get["properties"]["fields"]["items"])
    groups = _resolve_schema(spec, common_get["properties"]["field_groups"]["items"])
    assert {"name", "kind", "required", "description", "env_key", "default", "current"} <= set(fields["properties"])
    assert {"id", "title", "field_names"} <= set(groups["properties"])
    assert common_put == common_get
    raw_put = _response_data_schema(spec, f"{config_path}/raw", "put")
    assert raw_put == common_get
    assert "/pallas/api/plugins" in paths


def test_plugin_catalog_producer_keeps_nullable_and_open_metadata(monkeypatch) -> None:
    from packages.pb_webui import console_openapi_models as models

    row = _plugin_row_producer_fixture(monkeypatch)
    row_model = getattr(models, "PluginCatalogRow", None)
    assert row_model is not None, "插件目录生产行缺少 OpenAPI 契约模型"

    validated = row_model.model_validate(row)
    assert validated.metadata.name is None
    assert validated.metadata.extra == ["future"]
    assert validated.uninstall_kind is None
    assert validated.uninstall_target is None
    with pytest.raises(ValidationError, match="valid string"):
        row_model.model_validate({**row, "name": None})


def test_instances_producer_keeps_optional_alias_and_open_extensions(monkeypatch) -> None:
    from packages.pb_webui import console_openapi_models as models

    payload = _instances_producer_fixture(monkeypatch)
    model = getattr(models, "InstancesData", None)
    assert model is not None, "实例数据缺少 OpenAPI 契约模型"

    validated = model.model_validate(payload)
    assert validated.pallas_protocol is None
    assert "napcat" not in payload
    assert validated.protocol_extension.future_status == {"available": True}
    assert validated.bot_profiles["42"].future_profile_value == [1, None]


def test_config_and_governance_inner_models_are_structured_and_open() -> None:
    from packages.pb_webui.console_openapi_models import PluginGovernanceMenuItemData

    config_schema = PluginConfigData.model_json_schema()
    fields_ref = config_schema["properties"]["fields"]["items"]["$ref"]
    field_schema = config_schema["$defs"][fields_ref.rsplit("/", 1)[-1]]
    assert {"name", "kind", "default", "current"} <= set(field_schema["properties"])
    assert field_schema["additionalProperties"] is True
    field = PluginConfigData.model_validate({
        "plugin": "fixture",
        "fields": [{
            "name": "custom",
            "kind": "json",
            "required": False,
            "description": "",
            "env_key": "CUSTOM",
            "default": None,
            "current": {"future": [1, None]},
            "ui_order": {"future": 1},
            "ui_hidden": ["future"],
            "ui_widget": {"kind": "future"},
            "ui_gateway": {"mode": "split"},
        }],
    })
    assert field.fields[0].ui_order == {"future": 1}
    assert field.fields[0].ui_hidden == ["future"]

    governance_schema = PluginGovernanceData.model_json_schema()
    assert governance_schema["properties"]["perm_ui_filtered"]["$ref"]
    assert governance_schema["properties"]["limits_ui_filtered"]["$ref"]
    menu_item = PluginGovernanceMenuItemData.model_validate({
        "trigger_condition": ["future", "metadata"],
        "future_menu_value": {"enabled": True},
    })
    assert menu_item.trigger_condition == ["future", "metadata"]


def test_common_config_producers_match_the_form_contract(monkeypatch, tmp_path) -> None:
    from pydantic import BaseModel

    from pallas.console.webui import service_gateways_section, webui_env_section_payload
    from pallas.console.webui.env_sections import clear_webui_env_sections_cache
    from pallas.core.foundation.config import repo_settings

    class GatewayConfig(BaseModel):
        pallas_image_base_url: str = ""
        maa_public_base_url: str = ""
        sing_enable: bool = False

    monkeypatch.setattr(repo_settings, "_REPO_ROOT", tmp_path)
    monkeypatch.setattr(
        service_gateways_section,
        "_load_config_plugin",
        lambda _name: (GatewayConfig, GatewayConfig),
    )
    monkeypatch.setattr("pallas.console.webui.plugin_api.maybe_migrate_draw_config", lambda config: config)
    clear_webui_env_sections_cache()
    try:
        for section in (
            "llm",
            "ingress_dispatch",
            "service_gateways",
            "control_plane",
            "corpus_federation",
            "log_level",
        ):
            payload = webui_env_section_payload(section)
            validated = PluginConfigData.model_validate(payload)
            assert validated.plugin == payload["plugin"]
            assert len(validated.fields) == len(payload["fields"])
    finally:
        clear_webui_env_sections_cache()


def test_actual_route_json_preserves_open_config_values_and_absence(monkeypatch) -> None:
    from packages.pb_webui import common_config_api, instances_configs_api, plugins_console_api
    from packages.pb_webui.common_config_api import register_common_config_router
    from packages.pb_webui.instances_configs_api import register_instances_configs_router
    from packages.pb_webui.plugins_console_api import register_plugins_console_router

    row = _plugin_row_producer_fixture(monkeypatch)
    instances = _instances_producer_fixture(monkeypatch)
    field = {
        "name": "custom",
        "kind": "json",
        "required": False,
        "description": "",
        "env_key": "CUSTOM_VALUE",
        "default": None,
        "current": {"nested": [1, None]},
        "ui_group": None,
        "ui_order": {"extension": 1},
        "ui_hidden": ["future"],
        "ui_widget": {"kind": "future"},
        "ui_gateway": {"providers": ["open"]},
    }
    group = {"id": "general", "title": "通用", "field_names": ["custom"], "future_group_value": None}
    config = {"plugin": "fixture", "module": "fixture.config", "fields": [field], "field_groups": [group]}

    async def cached(*, key: str, loader, **_kwargs):
        return {"plugins": [row], "instances": instances}[key]

    async def cached_instances(*, key: str, loader, **_kwargs):
        return instances

    monkeypatch.setattr(plugins_console_api, "cached_read", cached)
    monkeypatch.setattr(instances_configs_api, "cached_read", cached_instances)
    monkeypatch.setattr(common_config_api, "check_pallas_write_token", lambda *_a, **_kw: None)
    monkeypatch.setattr("pallas.console.webui.env_sections.webui_env_section_payload", lambda *_a, **_kw: config)
    monkeypatch.setattr("pallas.console.webui.env_sections.apply_webui_env_section_patch", lambda *_a, **_kw: config)
    monkeypatch.setattr(
        "pallas.console.webui.env_sections.apply_webui_env_section_raw_toml",
        lambda *_a, **_kw: config,
    )

    app = FastAPI()
    cfg = Config()
    register_plugins_console_router(app.router, x="/pallas/api", plugin_config=cfg)
    register_instances_configs_router(app.router, x="/pallas/api", plugin_config=cfg)
    register_common_config_router(app.router, x="/pallas/api", plugin_config=cfg)
    client = TestClient(app)

    assert client.get("/pallas/api/plugins").json() == {"ok": True, "data": [row]}
    assert client.get("/pallas/api/instances").json() == {"ok": True, "data": instances}
    assert client.get("/pallas/api/common-config/fixture").json() == {"ok": True, "data": config}
    assert client.put("/pallas/api/common-config/fixture", json={"values": {}}).json() == {
        "ok": True,
        "data": config,
    }
    raw_response = client.put("/pallas/api/common-config/fixture/raw", json={"toml": "[env]"})
    assert raw_response.status_code == 200, raw_response.text
    raw_data = raw_response.json()["data"]
    assert raw_data["fields"] == [field]
    assert raw_data["field_groups"] == [group]
    assert raw_data["fields"][0]["ui_order"] == {"extension": 1}
    assert "napcat" not in raw_data

    minimal_field = {key: value for key, value in field.items() if not key.startswith("ui_")}
    minimal_config = {"plugin": "fixture", "module": "fixture.config", "fields": [minimal_field]}
    monkeypatch.setattr(plugins_console_api, "plugin_config_payload", lambda _name: minimal_config)
    monkeypatch.setattr(plugins_console_api, "check_pallas_write_token", lambda *_a, **_kw: None)
    monkeypatch.setattr(
        "pallas.console.webui.plugin_api.apply_plugin_config_raw_toml",
        lambda *_a, **_kw: minimal_config,
    )
    old_config_data = {
        **minimal_config,
        "unexpected_keys": [],
        "field_groups": [],
        "hot_reload": None,
        "gateway_editor": None,
        "supports_connectivity_check": None,
        "llm_model_admin": None,
        "dev_mode_hot_reload": None,
        "command_perm_ui": None,
        "command_limits_ui": None,
    }
    assert client.get("/pallas/api/plugins/fixture/config").json() == {
        "ok": True,
        "error": None,
        "data": old_config_data,
    }
    plugin_raw_response = client.put("/pallas/api/plugins/fixture/config/raw", json={"toml": "[env]"})
    assert plugin_raw_response.status_code == 200, plugin_raw_response.text
    assert plugin_raw_response.json() == {
        "ok": True,
        "error": None,
        "data": old_config_data,
    }
    monkeypatch.setattr(
        "pallas.console.webui.env_sections.apply_webui_env_section_raw_toml",
        lambda *_a, **_kw: minimal_config,
    )
    minimal_response = client.put("/pallas/api/common-config/fixture/raw", json={"toml": "[env]"})
    assert minimal_response.status_code == 200, minimal_response.text
    assert minimal_response.json() == {"ok": True, "error": None, "data": old_config_data}


def test_governance_get_and_put_routes_keep_their_distinct_json_shapes(monkeypatch) -> None:
    from packages.pb_webui import plugins_console_api
    from packages.pb_webui.plugins_console_api import register_plugins_console_router

    command_id = "fixture.run"
    command = {"command_id": command_id, "label": "运行"}
    permission_command = {
        **command,
        "default_level": "everyone",
        "effective_level": "staff",
    }
    limit_command = {
        **command,
        "default_cd_sec": 3,
        "effective_cd_sec": 9,
    }
    permission_ui = {
        "levels": [{"id": "everyone", "label": "所有人"}],
        "plugins": [{
            "plugin": "fixture",
            "title": "Fixture",
            "commands": [permission_command],
            "future_permission_value": {"open": True},
        }],
    }
    limits_ui = {
        "plugins": [{
            "plugin": "fixture",
            "title": "Fixture",
            "commands": [limit_command],
        }],
        "future_limits_value": [1, None],
    }
    plugin_row = {
        "plugin": "fixture",
        "title": "Fixture",
        "commands": [command],
        "reload_policy": "config_only",
        "activation_policy": "hot-reloadable",
    }
    catalog_row = {
        "name": "fixture",
        "global_disable_protected": True,
        "help_ignored": True,
        "metadata": {"extra": {"menu_data": [{"trigger_condition": "未来扩展"}]}},
    }

    monkeypatch.setattr(plugins_console_api, "_list_plugins_dict", lambda: [catalog_row])
    monkeypatch.setattr(plugins_console_api, "check_pallas_write_token", lambda *_a, **_kw: None)
    monkeypatch.setattr("pallas.console.webui.plugin_governance.canonical_plugin_name", lambda name: name)
    monkeypatch.setattr(
        "pallas.core.plugin_capabilities.build_plugin_capabilities_ui",
        lambda: {"plugins": [plugin_row]},
    )
    monkeypatch.setattr("packages.help.visibility.load_help_hidden_plugins", lambda: ["fixture"])
    monkeypatch.setattr("packages.help.global_disable.load_global_disabled_plugins", lambda: ["fixture"])
    monkeypatch.setattr("packages.help.global_disable.global_disabled_plugins_revision", lambda _items: "revision")
    monkeypatch.setattr("pallas.core.perm.config.get_cmd_perm_config", lambda: SimpleNamespace(
        command_permission_overrides={},
    ))
    monkeypatch.setattr("pallas.core.limits.config.get_command_limits_config", lambda: SimpleNamespace(
        command_limit_overrides={},
    ))
    monkeypatch.setattr("pallas.core.perm.schema.build_command_perm_ui", lambda _overrides: permission_ui)
    monkeypatch.setattr("pallas.core.limits.schema.build_command_limits_ui", lambda _overrides: limits_ui)

    async def blocked(_plugin: str) -> list[int]:
        return [77]

    monkeypatch.setattr("pallas.core.perm.plugin_acl.list_plugin_blocked_user_ids", blocked)
    monkeypatch.setattr(plugins_console_api, "drop_read_cache", lambda _keys: None)

    app = FastAPI()
    register_plugins_console_router(app.router, x="/pallas/api", plugin_config=Config())
    client = TestClient(app)

    get_response = client.get("/pallas/api/plugins/fixture/governance")
    assert get_response.status_code == 200, get_response.text
    get_json = get_response.json()
    assert get_json == {
        "ok": True,
        "error": None,
        "data": {
            "plugin": "fixture",
            "title": "Fixture",
            "commands": [command],
            "menu_items": [{"trigger_condition": "未来扩展"}],
            "runtime": {
                "global_disable": True,
                "global_disable_revision": "revision",
                "help_hidden": True,
                "global_disable_protected": True,
                "help_ignored": True,
            },
            "perm_ui_filtered": {
                "levels": permission_ui["levels"],
                "plugins": [permission_ui["plugins"][0]],
            },
            "limits_ui_filtered": {"plugins": [limits_ui["plugins"][0]]},
            "blocked_user_ids": [77],
            "reload_policy": "config_only",
            "activation_policy": "hot-reloadable",
        },
    }

    put_response = client.put("/pallas/api/plugins/fixture/governance", json={})
    assert put_response.status_code == 200, put_response.text
    assert put_response.json() == {
        "ok": True,
        "data": {
            "plugin": "fixture",
            "command_permission_overrides": {},
            "command_limit_overrides": {},
            "blocked_user_ids": [77],
            "runtime": {
                "global_disable": True,
                "global_disable_revision": "revision",
                "help_hidden": True,
            },
        },
    }
