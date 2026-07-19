from __future__ import annotations

import json

from pallas.core.platform.bot_runtime.load_policy import merge_startup_skip_plugins


def _patch_help_data_dir(monkeypatch, tmp_path):
    from pallas.core.platform.bot_runtime import startup_global_disable

    help_dir = tmp_path / "help"
    help_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(
        startup_global_disable,
        "plugin_data_dir",
        lambda name, create=True: help_dir if name == "help" else tmp_path / name,
    )
    monkeypatch.setattr(
        "pallas.core.storage.deploy_store.plugin_data_dir",
        lambda name, create=True: help_dir if name == "help" else tmp_path / name,
    )
    startup_global_disable.startup_global_disabled_plugin_names.cache_clear()
    return help_dir


def test_merge_startup_skip_plugins_reads_plugin_storage(tmp_path, monkeypatch) -> None:
    help_dir = _patch_help_data_dir(monkeypatch, tmp_path)
    (help_dir / "plugin_storage.json").write_text(
        json.dumps({"global_disabled_plugins": ["chat", "ollama"]}),
        encoding="utf-8",
    )

    merged = merge_startup_skip_plugins(frozenset({"maa_hub"}))
    assert merged == frozenset({"maa_hub", "chat", "ollama"})


def test_merge_startup_skip_plugins_migrates_legacy_json(tmp_path, monkeypatch) -> None:
    help_dir = _patch_help_data_dir(monkeypatch, tmp_path)
    (help_dir / "global_disabled_plugins.json").write_text(
        '{"disabled_plugins": ["chat", "ollama"]}',
        encoding="utf-8",
    )

    merged = merge_startup_skip_plugins(frozenset({"maa_hub"}))
    assert merged == frozenset({"maa_hub", "chat", "ollama"})
    assert (help_dir / "plugin_storage.json").is_file()
    assert not (help_dir / "global_disabled_plugins.json").is_file()


def test_merge_startup_skip_plugins_keeps_protected_out(tmp_path, monkeypatch) -> None:
    help_dir = _patch_help_data_dir(monkeypatch, tmp_path)
    (help_dir / "plugin_storage.json").write_text(
        json.dumps({"global_disabled_plugins": ["help", "ingress_gate", "chat"]}),
        encoding="utf-8",
    )

    merged = merge_startup_skip_plugins(frozenset())
    assert "help" not in merged
    assert "ingress_gate" not in merged
    assert "chat" in merged
