from __future__ import annotations

from src.platform.bot_runtime.load_policy import merge_startup_skip_plugins


def test_merge_startup_skip_plugins_merges_global_disable(tmp_path, monkeypatch) -> None:
    from src.platform.bot_runtime import startup_global_disable

    monkeypatch.setattr(
        startup_global_disable,
        "plugin_data_dir",
        lambda _name, create=True: tmp_path / "help",
    )
    startup_global_disable.startup_global_disabled_plugin_names.cache_clear()
    (tmp_path / "help").mkdir(parents=True, exist_ok=True)
    (tmp_path / "help" / "global_disabled_plugins.json").write_text(
        '{"disabled_plugins": ["chat", "ollama"]}',
        encoding="utf-8",
    )

    merged = merge_startup_skip_plugins(frozenset({"maa_hub"}))
    assert merged == frozenset({"maa_hub", "chat", "ollama"})


def test_merge_startup_skip_plugins_keeps_protected_out(tmp_path, monkeypatch) -> None:
    from src.platform.bot_runtime import startup_global_disable

    monkeypatch.setattr(
        startup_global_disable,
        "plugin_data_dir",
        lambda _name, create=True: tmp_path / "help",
    )
    startup_global_disable.startup_global_disabled_plugin_names.cache_clear()
    (tmp_path / "help").mkdir(parents=True, exist_ok=True)
    (tmp_path / "help" / "global_disabled_plugins.json").write_text(
        '{"disabled_plugins": ["help", "ingress_gate", "chat"]}',
        encoding="utf-8",
    )

    merged = merge_startup_skip_plugins(frozenset())
    assert "help" not in merged
    assert "ingress_gate" not in merged
    assert "chat" in merged
