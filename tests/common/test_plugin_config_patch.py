from typing import Literal

import pytest
from pydantic import BaseModel, Field, ValidationError

from pallas.console.webui.plugin_api import (
    find_loaded_plugin,
    format_validation_error,
    normalize_patch_value,
    plugin_config_model_by_name,
    plugin_config_payload,
    plugin_field_env_key,
    plugin_nested_field_leaves,
)


class SampleConfig(BaseModel):
    tags: list[int] = Field(default_factory=list)
    ratio: float = Field(default=1.0, ge=0.0)
    interval_sec: Literal[60, 120, 300, 600, 900, 1800, 3600] = 300
    mode: Literal["auto", "session"] = "auto"


class NestedInner(BaseModel):
    github_proxy_url: str = ""
    check_res_update: bool = False


class NestedConfig(BaseModel):
    skland: NestedInner = Field(default_factory=NestedInner)
    gacha_render_max: int = 30


def test_normalize_patch_null_list_uses_empty_list() -> None:
    field = SampleConfig.model_fields["tags"]
    assert normalize_patch_value(field, None) == []


def test_normalize_patch_coerces_numeric_literal_string() -> None:
    field = SampleConfig.model_fields["interval_sec"]
    assert normalize_patch_value(field, "1800") == 1800
    assert normalize_patch_value(field, 1800) == 1800
    assert normalize_patch_value(field, 1800.0) == 1800


def test_normalize_patch_keeps_string_literal() -> None:
    field = SampleConfig.model_fields["mode"]
    assert normalize_patch_value(field, "session") == "session"


def test_plugin_field_env_key_repeater_learn() -> None:
    assert plugin_field_env_key("repeater", "learn_concurrency") == "PALLAS_REPEATER_LEARN_CONCURRENCY"
    assert plugin_field_env_key("repeater", "answer_threshold") == "ANSWER_THRESHOLD"
    assert plugin_field_env_key("sing", "sing_enable") == "SING_ENABLE"


def test_nested_field_leaves_flattens_nested_model() -> None:
    """嵌套 BaseModel 字段应展开为叶字段，env 键用 ``__`` 分隔前缀。"""
    leaves = plugin_nested_field_leaves(NestedConfig)
    by_name = {leaf["name"]: leaf for leaf in leaves}
    # 嵌套字段展开为 skland.<field>
    assert "skland.github_proxy_url" in by_name
    assert "skland.check_res_update" in by_name
    # 顶层标量字段保留原名
    assert "gacha_render_max" in by_name
    # 嵌套字段 env 键带 SKLAND 前缀（大写 + __ 分隔）；标量不带前缀
    assert by_name["skland.github_proxy_url"]["env_key"] == "SKLAND__GITHUB_PROXY_URL"
    assert by_name["gacha_render_max"]["env_key"] == "GACHA_RENDER_MAX"


def test_nested_plugin_config_payload_expands_nested_model(monkeypatch) -> None:
    """plugin_config_payload 对嵌套 Config 展开为叶字段行。"""
    from pallas.console.webui import plugin_api

    def _fake_model_by_name(name):
        return object(), "nonebot_plugin_skland", NestedConfig

    def _fake_read_current(module_name, cfg_cls):
        return NestedConfig(
            skland=NestedInner(github_proxy_url="http://proxy", check_res_update=True), gacha_render_max=42
        )

    monkeypatch.setattr(plugin_api, "plugin_config_model_by_name", _fake_model_by_name)
    monkeypatch.setattr(plugin_api, "read_current_plugin_config", _fake_read_current)

    payload = plugin_config_payload("skland")

    names = [f["name"] for f in payload["fields"]]
    assert "skland.github_proxy_url" in names
    assert "skland.check_res_update" in names
    assert "gacha_render_max" in names
    by_name = {f["name"]: f for f in payload["fields"]}
    # 展开后字段 name 为点路径，env_key 带 __ 前缀
    assert by_name["skland.github_proxy_url"]["env_key"] == "SKLAND__GITHUB_PROXY_URL"
    assert by_name["skland.check_res_update"]["current"] is True
    assert by_name["gacha_render_max"]["current"] == 42


def test_apply_nested_plugin_config_patch_rebuilds_nested(monkeypatch) -> None:
    """apply 对嵌套点路径保存时重建嵌套 dict 并写 __ 分隔 env 键。"""
    from pallas.console.webui import plugin_api

    def _fake_model_by_name(name):
        return object(), "nonebot_plugin_skland", NestedConfig

    def _fake_read_current(module_name, cfg_cls):
        return NestedConfig()

    upserted: dict[str, str] = {}

    def _fake_upsert(items):
        upserted.update(items)

    monkeypatch.setattr(plugin_api, "plugin_config_model_by_name", _fake_model_by_name)
    monkeypatch.setattr(plugin_api, "read_current_plugin_config", _fake_read_current)
    monkeypatch.setattr(plugin_api, "upsert_repo_settings_items", _fake_upsert)
    monkeypatch.setattr(plugin_api, "reload_plugin_config", lambda _m: False)
    monkeypatch.setattr(
        "pallas.core.plugin_reload.metadata_index.reload_metadata_after_plugin_config_save",
        lambda _n: None,
    )

    payload = plugin_api.apply_plugin_config_patch(
        "skland",
        {"skland.github_proxy_url": "http://new-proxy", "gacha_render_max": 99},
    )

    # 嵌套 env 键用 __ 前缀，标量用原名大写
    assert upserted["SKLAND__GITHUB_PROXY_URL"] == "http://new-proxy"
    assert upserted["GACHA_RENDER_MAX"] == "99"
    # payload 回传 current 展开正确
    by_name = {f["name"]: f for f in payload["fields"]}
    assert by_name["skland.github_proxy_url"]["current"] == "http://new-proxy"
    assert by_name["gacha_render_max"]["current"] == 99


def test_format_validation_error_includes_field() -> None:
    with pytest.raises(ValidationError) as exc:
        SampleConfig(ratio=-1)

    msg = format_validation_error(exc.value)
    assert "ratio" in msg


def test_find_loaded_plugin_matches_official_pip_module(monkeypatch) -> None:
    class FakeLoadedPlugin:
        name = "pallas_plugin_draw"
        module = type("Mod", (), {"__name__": "pallas_plugin_draw"})()

    monkeypatch.setattr("pallas.console.webui.plugin_api.get_loaded_plugins", lambda: [FakeLoadedPlugin()])

    matched = find_loaded_plugin("draw")

    assert matched is not None
    assert matched.name == "pallas_plugin_draw"


def test_plugin_config_model_by_name_resolves_official_pip_module(monkeypatch) -> None:
    class Config(BaseModel):
        enabled: bool = True

    class FakeLoadedPlugin:
        name = "pallas_plugin_draw"
        module = type("Mod", (), {"__name__": "pallas_plugin_draw"})()

    monkeypatch.setattr("pallas.console.webui.plugin_api.get_loaded_plugins", lambda: [FakeLoadedPlugin()])
    monkeypatch.setattr(
        "importlib.import_module",
        lambda module_name: (
            type("CfgModule", (), {"Config": Config})() if module_name == "pallas_plugin_draw.config" else None
        ),
    )

    plugin_obj, module_name, cfg_cls = plugin_config_model_by_name("draw")

    assert plugin_obj is not None
    assert module_name == "pallas_plugin_draw"
    assert cfg_cls is Config
