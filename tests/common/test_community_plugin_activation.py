from __future__ import annotations

from unittest.mock import MagicMock


def test_hot_load_extra_dir_plugin_skips_when_already_loaded(monkeypatch, tmp_path):
    from pallas.core.platform.bot_runtime import plugin_loader

    monkeypatch.setattr(
        plugin_loader,
        "runtime_loaded_short_names",
        lambda: {"interact"},
    )
    assert plugin_loader.hot_load_extra_dir_plugin("interact") is False


def test_hot_load_extra_dir_plugin_loads_from_extra_dir(monkeypatch, tmp_path):
    from pallas.core.platform.bot_runtime import plugin_loader

    plugin_dir = tmp_path / "local" / "plugins" / "demo"
    plugin_dir.mkdir(parents=True)
    (plugin_dir / "__init__.py").write_text("# demo\n", encoding="utf-8")

    monkeypatch.setattr(plugin_loader, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(
        plugin_loader,
        "runtime_loaded_short_names",
        lambda: set(),
    )
    monkeypatch.setattr(
        plugin_loader,
        "load_apscheduler_plugin_first",
        lambda **kwargs: False,
    )
    monkeypatch.setattr(
        "pallas.core.foundation.config.repo_settings.resolve_extra_plugin_dirs",
        lambda: ["local/plugins"],
    )
    monkeypatch.setattr(
        "pallas.core.plugin_reload.metadata_index.reload_plugin_metadata_index",
        lambda: None,
    )

    fake_plugin = MagicMock()
    fake_plugin.module = MagicMock(__name__="demo")
    monkeypatch.setattr(
        plugin_loader.nonebot,
        "load_plugin",
        lambda _path: fake_plugin,
    )
    monkeypatch.setattr(plugin_loader, "load_bundled_plugin_entry_submodules", lambda _name: None)

    assert plugin_loader.hot_load_extra_dir_plugin("demo") is True
