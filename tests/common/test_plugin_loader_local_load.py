from __future__ import annotations

import json
from types import SimpleNamespace

from pallas.core.platform.bot_runtime import plugin_loader


def test_load_discovered_plugin_modules_applies_skip_rules(monkeypatch):
    calls: list[tuple[str, str, set[str]]] = []
    records: list[tuple[str, tuple[object, ...]]] = []

    def fake_load(module_path: str, *, role_label: str, loaded_short: set[str]) -> bool:
        calls.append((module_path, role_label, set(loaded_short)))
        loaded_short.add(module_path.rsplit(".", 1)[-1])
        return True

    monkeypatch.setattr(plugin_loader, "_load_plugin_module", fake_load)
    monkeypatch.setattr(
        plugin_loader,
        "logger",
        SimpleNamespace(info=lambda message, *args: records.append((message, args))),
    )

    loaded_short = {"already"}
    count = plugin_loader._load_discovered_plugin_modules(
        role_label="worker",
        module_paths=[
            "packages.skip_by_path",
            "packages.keep",
            "packages.skip_me",
            "packages.already",
        ],
        skip_short=frozenset({"skip_me"}),
        skip_module_paths=frozenset({"packages.skip_by_path"}),
        loaded_short=loaded_short,
    )

    assert count == 1
    assert calls == [("packages.keep", "worker", {"already"})]
    assert loaded_short == {"already", "keep"}
    assert records == [
        ("跳过 {}：配置排除", ("packages.skip_by_path",)),
        ("跳过 {}：配置禁用", ("packages.skip_me",)),
        ("跳过 {}：同名插件已加载", ("packages.already",)),
    ]


def test_load_discovered_plugin_modules_skips_canonical_alias(monkeypatch):
    calls: list[str] = []

    def fake_load(module_path: str, *, role_label: str, loaded_short: set[str]) -> bool:
        calls.append(module_path)
        loaded_short.add(plugin_loader._load_slot_key(module_path))
        return True

    monkeypatch.setattr(plugin_loader, "_load_plugin_module", fake_load)

    loaded_short = {"draw"}
    count = plugin_loader._load_discovered_plugin_modules(
        role_label="worker",
        module_paths=["pallas_plugin_draw"],
        skip_short=frozenset(),
        loaded_short=loaded_short,
    )

    assert count == 0
    assert calls == []
    assert loaded_short == {"draw"}


def test_load_discovered_plugin_modules_skips_src_bundled_when_pip_alias_loaded(monkeypatch):
    calls: list[str] = []

    def fake_load(module_path: str, *, role_label: str, loaded_short: set[str]) -> bool:
        calls.append(module_path)
        loaded_short.add(plugin_loader._load_slot_key(module_path))
        return True

    monkeypatch.setattr(plugin_loader, "_load_plugin_module", fake_load)

    loaded_short = {"duel"}
    count = plugin_loader._load_discovered_plugin_modules(
        role_label="worker",
        module_paths=["packages.duel"],
        skip_short=frozenset(),
        loaded_short=loaded_short,
    )

    assert count == 0
    assert calls == []
    assert loaded_short == {"duel"}


def test_load_plugin_module_logs_neutral_message_when_module_missing(monkeypatch):
    records: list[tuple[str, tuple[object, ...]]] = []

    monkeypatch.setattr(
        "pallas.core.platform.bot_runtime.plugin_loader.importlib.util.find_spec",
        lambda _module_path: None,
    )
    monkeypatch.setattr(
        plugin_loader,
        "logger",
        SimpleNamespace(error=lambda message, *args: records.append((message, args))),
    )

    loaded = plugin_loader._load_plugin_module(
        "packages.relogin_bot",
        role_label="hub",
        loaded_short=set(),
    )

    assert loaded is False
    assert records == [
        (
            "跳过 {}：未发现模块",
            ("packages.relogin_bot",),
        )
    ]
    assert "uv sync" not in records[0][0]


def test_load_plugin_module_records_failure_when_nonebot_swallows_import_error(monkeypatch):
    records: list[tuple[str, tuple[object, ...]]] = []
    failures: list[str] = []

    monkeypatch.setattr(
        "pallas.core.platform.bot_runtime.plugin_loader.importlib.util.find_spec",
        lambda _module_path: SimpleNamespace(),
    )
    monkeypatch.setattr(plugin_loader.nonebot, "load_plugin", lambda _path: None)
    monkeypatch.setattr(
        plugin_loader,
        "logger",
        SimpleNamespace(warning=lambda message, *args: records.append((message, args))),
    )
    monkeypatch.setattr(
        plugin_loader,
        "record_startup_plugin_load_failure",
        lambda module_path: failures.append(module_path),
    )

    loaded = plugin_loader._load_plugin_module(
        "packages.broken",
        role_label="worker",
        loaded_short=set(),
    )

    assert loaded is False
    assert failures == ["packages.broken"]
    assert records == [
        (
            "启动：{} 加载 {} 失败",
            ("worker", "packages.broken"),
        )
    ]


def test_plugin_load_diagnostics_keeps_failures_and_slow_plugins() -> None:
    plugin_loader.reset_startup_plugin_load_diagnostics()
    plugin_loader.record_startup_plugin_load_failure("packages.weather")
    plugin_loader.record_startup_plugin_load_success("packages.ai_media", elapsed_sec=1.42)
    plugin_loader.record_startup_plugin_load_success("packages.pb_core", elapsed_sec=0.02)

    assert plugin_loader.startup_plugin_load_diagnostic_facts() == {
        "plugin_failures": "weather",
        "plugin_slow": "ai_media=1.42",
    }


def test_split_site_local_plugin_dirs_keeps_custom_dirs_separate() -> None:
    site_local, custom = plugin_loader.split_site_local_plugin_dirs(["local/plugins", "plugins/custom"])

    assert site_local == ["local/plugins"]
    assert custom == ["plugins/custom"]


def test_classify_site_local_plugins_separates_community_plugin_directories(tmp_path, monkeypatch) -> None:
    community = tmp_path / "interact"
    community.mkdir()
    (community / "community-index.entry.json").write_text(json.dumps({"id": "interact"}), encoding="utf-8")
    local = tmp_path / "private_plugin"
    local.mkdir()
    monkeypatch.setattr(plugin_loader, "plugin_directory_git_origin", lambda _path: "")

    local_count, community_count = plugin_loader.classify_site_local_plugins([community, local])

    assert local_count == 1
    assert community_count == 1


def test_community_plugin_directory_accepts_external_git_origin(tmp_path, monkeypatch) -> None:
    plugin_dir = tmp_path / "bilibili_dynamic"
    plugin_dir.mkdir()
    monkeypatch.setattr(
        plugin_loader,
        "plugin_directory_git_origin",
        lambda _path: "https://github.com/Blackish-Red/pallas-plugin-bilibili.git",
    )

    assert plugin_loader.is_community_plugin_directory(plugin_dir) is True
