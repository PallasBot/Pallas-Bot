from __future__ import annotations

import pytest

from pallas.core.platform.plugin_runtime import resolve
from pallas.core.platform.plugin_runtime.resolve import (
    bundled_or_extra_module_prefix,
    import_plugin_submodule,
    loaded_plugin_module_prefix,
)


def test_bundled_or_extra_module_prefix_falls_back_to_pallas_plugin_draw() -> None:
    prefix = bundled_or_extra_module_prefix("draw")
    pytest.importorskip("pallas_plugin_draw")
    assert prefix == "pallas_plugin_draw"


def test_import_plugin_submodule_draw_config() -> None:
    pytest.importorskip("pallas_plugin_draw")
    mod = import_plugin_submodule("draw", "config")
    assert mod.__name__ == "pallas_plugin_draw.config"
    assert hasattr(mod, "active_image_gen_settings")


def test_bundled_or_extra_module_prefix_prefers_direct_relogin_module() -> None:
    pytest.importorskip("pallas_plugin_relogin_bot")
    prefix = bundled_or_extra_module_prefix("relogin_bot")
    assert prefix == "pallas_plugin_relogin_bot"


def test_bundled_or_extra_module_prefix_uses_registry_canonical_result_for_relogin(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: list[str] = []

    def fake_find_spec(name: str):
        seen.append(name)
        return object() if name == "pallas_plugin_relogin_bot" else None

    monkeypatch.setattr(resolve.importlib.util, "find_spec", fake_find_spec)

    assert bundled_or_extra_module_prefix("relogin_bot") == "pallas_plugin_relogin_bot"
    assert seen == ["packages.relogin_bot", "pallas_plugin_relogin_bot"]


def test_bundled_or_extra_module_prefix_uses_canonical_identity_for_bot_status(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        resolve.importlib.util,
        "find_spec",
        lambda name: object() if name == "pallas_plugin_bot_status" else None,
    )

    assert bundled_or_extra_module_prefix("bot_status") == "pallas_plugin_bot_status"


def test_loaded_plugin_module_prefix_matches_loaded_plugin_via_canonical_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    loaded = [
        type(
            "LoadedPlugin",
            (),
            {
                "name": "pallas_plugin_relogin_bot",
                "module": type("Module", (), {"__name__": "pallas_plugin_relogin_bot"})(),
            },
        )(),
    ]

    monkeypatch.setattr(resolve, "get_loaded_plugins", lambda: loaded)

    assert loaded_plugin_module_prefix("relogin_bot") == "pallas_plugin_relogin_bot"


def test_unknown_plugin_falls_back_without_registry_keyerror(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(resolve, "get_loaded_plugins", list)
    monkeypatch.setattr(resolve.importlib.util, "find_spec", lambda name: None)

    assert loaded_plugin_module_prefix("custom_plugin") is None
    assert bundled_or_extra_module_prefix("custom_plugin") == "packages.custom_plugin"
