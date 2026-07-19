import pytest
from pydantic import BaseModel, Field, ValidationError

from pallas.console.webui.plugin_api import (
    find_loaded_plugin,
    format_validation_error,
    normalize_patch_value,
    plugin_config_model_by_name,
    plugin_field_env_key,
)


class SampleConfig(BaseModel):
    tags: list[int] = Field(default_factory=list)
    ratio: float = Field(default=1.0, ge=0.0)


def test_normalize_patch_null_list_uses_empty_list() -> None:
    field = SampleConfig.model_fields["tags"]
    assert normalize_patch_value(field, None) == []


def test_plugin_field_env_key_repeater_learn() -> None:
    assert plugin_field_env_key("repeater", "learn_concurrency") == "PALLAS_REPEATER_LEARN_CONCURRENCY"
    assert plugin_field_env_key("repeater", "answer_threshold") == "ANSWER_THRESHOLD"
    assert plugin_field_env_key("sing", "sing_enable") == "SING_ENABLE"


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
