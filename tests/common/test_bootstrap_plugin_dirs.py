from __future__ import annotations

from pallas.core.foundation.config.repo_settings import (
    read_bootstrap_extra_plugin_dirs,
    read_bootstrap_load_bundled_extra_plugins_mode,
    resolve_extra_plugin_dirs,
)


def test_read_bootstrap_extra_plugin_dirs_empty_when_missing(tmp_path, monkeypatch) -> None:
    root = tmp_path / "repo"
    (root / "config").mkdir(parents=True)
    monkeypatch.setattr("pallas.core.foundation.config.repo_settings._REPO_ROOT", root)
    assert read_bootstrap_extra_plugin_dirs() == []


def test_read_bootstrap_extra_plugin_dirs_from_toml(tmp_path, monkeypatch) -> None:
    root = tmp_path / "repo"
    cfg = root / "config" / "pallas.toml"
    cfg.parent.mkdir(parents=True)
    cfg.write_text(
        """
[bootstrap]
extra_plugin_dirs = ["local/plugins", "./local/plugins", "plugins/custom"]
""",
        encoding="utf-8",
    )
    monkeypatch.setattr("pallas.core.foundation.config.repo_settings._REPO_ROOT", root)
    assert read_bootstrap_extra_plugin_dirs() == ["local/plugins", "plugins/custom"]


def test_read_bootstrap_extra_plugin_dirs_top_level_fallback(tmp_path, monkeypatch) -> None:
    root = tmp_path / "repo"
    cfg = root / "config" / "pallas.toml"
    cfg.parent.mkdir(parents=True)
    cfg.write_text(
        """
extra_plugin_dirs = ["local/plugins"]
""",
        encoding="utf-8",
    )
    monkeypatch.setattr("pallas.core.foundation.config.repo_settings._REPO_ROOT", root)
    assert read_bootstrap_extra_plugin_dirs() == ["local/plugins"]


def test_read_bootstrap_load_bundled_default_auto(tmp_path, monkeypatch) -> None:
    root = tmp_path / "repo"
    (root / "config").mkdir(parents=True)
    monkeypatch.setattr("pallas.core.foundation.config.repo_settings._REPO_ROOT", root)
    monkeypatch.delenv("PALLAS_LOAD_BUNDLED_EXTRA", raising=False)
    assert read_bootstrap_load_bundled_extra_plugins_mode() == "auto"


def test_resolve_extra_plugin_dirs_auto_local(tmp_path, monkeypatch) -> None:
    root = tmp_path / "repo"
    (root / "config").mkdir(parents=True)
    plugin_root = root / "local" / "plugins" / "demo"
    plugin_root.mkdir(parents=True)
    (plugin_root / "__init__.py").write_text("", encoding="utf-8")
    monkeypatch.setattr("pallas.core.foundation.config.repo_settings._REPO_ROOT", root)
    assert resolve_extra_plugin_dirs() == ["local/plugins"]
