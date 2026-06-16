from src.console.webui.plugin_catalog import (
    build_plugin_catalog_rows,
    discover_extra_plugin_packages,
    discover_plugin_packages,
    discover_pyproject_plugin_modules,
    expected_loaded_in_catalog_process,
    infer_plugin_source,
    package_load_role,
    plugin_source_from_module_path,
)


def test_discover_includes_draw():
    pkgs = discover_plugin_packages()
    assert "draw" in pkgs
    assert "pallas_webui" in pkgs
    assert "ingress_gate" not in pkgs


def test_package_load_role_sharded(monkeypatch):
    monkeypatch.setenv("PALLAS_SHARD_ENABLED", "true")
    monkeypatch.setenv("PALLAS_BOT_ROLE", "hub")
    from src.platform.shard.registry.config import get_shard_registry_settings

    get_shard_registry_settings.cache_clear()
    assert package_load_role("draw") == "worker"
    assert package_load_role("ingress_gate") == "worker"
    assert package_load_role("pallas_webui") == "hub"


def test_expected_loaded_in_catalog_hub_vs_worker():
    assert expected_loaded_in_catalog_process("worker", "hub") is False
    assert expected_loaded_in_catalog_process("hub", "hub") is True
    assert expected_loaded_in_catalog_process("infra", "hub") is True
    assert expected_loaded_in_catalog_process("worker", "worker") is True
    assert expected_loaded_in_catalog_process("hub", "worker") is False


def test_expected_loaded_in_catalog_unified():
    assert expected_loaded_in_catalog_process("both", "unified") is True
    assert expected_loaded_in_catalog_process("infra", "unified") is True
    assert expected_loaded_in_catalog_process("hub", "unified") is False
    assert expected_loaded_in_catalog_process("worker", "unified") is False
    assert expected_loaded_in_catalog_process("internal", "unified") is False


def test_catalog_hides_shard_only_in_unified(monkeypatch):
    monkeypatch.delenv("PALLAS_SHARD_ENABLED", raising=False)
    monkeypatch.delenv("PALLAS_BOT_ROLE", raising=False)
    monkeypatch.setattr(
        "src.foundation.config.repo_settings.read_bootstrap_extra_plugin_dirs",
        list,
    )
    from src.platform.shard.registry.config import get_shard_registry_settings

    get_shard_registry_settings.cache_clear()
    rows = build_plugin_catalog_rows()
    names = {r["name"] for r in rows}
    assert "relogin_forward" not in names
    assert "maa_hub" not in names
    assert "ingress_gate" not in names
    assert "pallas_console_metrics" not in names
    assert "relogin_bot" in names
    assert "maa" in names
    assert rows[0]["catalog_process_role"] == "unified"


def test_catalog_shows_shard_only_on_sharded_hub(monkeypatch):
    monkeypatch.setenv("PALLAS_SHARD_ENABLED", "true")
    monkeypatch.setenv("PALLAS_BOT_ROLE", "hub")
    monkeypatch.setattr(
        "src.foundation.config.repo_settings.read_bootstrap_extra_plugin_dirs",
        list,
    )
    from src.platform.shard.registry.config import get_shard_registry_settings

    get_shard_registry_settings.cache_clear()
    rows = build_plugin_catalog_rows()
    names = {r["name"] for r in rows}
    assert "relogin_forward" in names
    assert "maa_hub" in names
    assert "ingress_gate" not in names


def test_catalog_lists_worker_plugin(monkeypatch):
    monkeypatch.setenv("PALLAS_SHARD_ENABLED", "true")
    monkeypatch.setenv("PALLAS_BOT_ROLE", "hub")
    monkeypatch.setattr(
        "src.foundation.config.repo_settings.read_bootstrap_extra_plugin_dirs",
        list,
    )
    from src.platform.shard.registry.config import get_shard_registry_settings

    get_shard_registry_settings.cache_clear()
    rows = build_plugin_catalog_rows()
    by_name = {r["name"]: r for r in rows}
    assert "duel" in by_name
    assert by_name["duel"]["load_role"] == "worker"
    assert by_name["duel"]["metadata"] is not None
    assert by_name["duel"]["plugin_source"] == "extra"
    assert by_name["duel"].get("extra_package") == "pallas-plugin-duel"
    assert by_name["duel"]["catalog_process_role"] == "hub"
    assert by_name["duel"]["expected_in_catalog_process"] is False
    assert by_name["pallas_webui"]["expected_in_catalog_process"] is True


def test_infer_plugin_source_local_dir(tmp_path, monkeypatch) -> None:
    root = tmp_path / "repo"
    pkg = root / "local" / "plugins" / "demo"
    pkg.mkdir(parents=True)
    (pkg / "__init__.py").write_text("x = 1\n", encoding="utf-8")
    monkeypatch.setattr("src.console.webui.plugin_catalog.PROJECT_ROOT", root)
    monkeypatch.setattr(
        "src.foundation.config.repo_settings.read_bootstrap_extra_plugin_dirs",
        lambda: ["local/plugins"],
    )
    extra = discover_extra_plugin_packages()
    assert "demo" in extra
    src, dir_posix = infer_plugin_source("demo", None, extra_pkgs=extra)
    assert src == "local"
    assert dir_posix == "local/plugins/demo"


def test_plugin_source_from_core_path() -> None:
    from src.foundation.paths import PROJECT_ROOT

    main_py = PROJECT_ROOT / "src" / "plugins" / "help" / "__init__.py"
    assert main_py.is_file()
    assert plugin_source_from_module_path(str(main_py)) == "core"


def test_discover_pyproject_includes_status():
    modules = discover_pyproject_plugin_modules()
    assert "nonebot_plugin_status" in modules


def test_catalog_lists_pyproject_status_on_hub(monkeypatch):
    monkeypatch.setenv("PALLAS_SHARD_ENABLED", "true")
    monkeypatch.setenv("PALLAS_BOT_ROLE", "hub")
    monkeypatch.setattr(
        "src.foundation.config.repo_settings.read_bootstrap_extra_plugin_dirs",
        list,
    )
    from src.platform.shard.registry.config import get_shard_registry_settings

    get_shard_registry_settings.cache_clear()
    rows = build_plugin_catalog_rows()
    by_name = {r["name"]: r for r in rows}
    assert "nonebot_plugin_status" in by_name
    row = by_name["nonebot_plugin_status"]
    assert row["plugin_source"] == "pip"
    assert row["load_role"] == "infra"


def test_resolve_catalog_prefers_local_draw(tmp_path, monkeypatch) -> None:
    root = tmp_path / "repo"
    local_pkg = root / "local" / "plugins" / "draw"
    local_pkg.mkdir(parents=True)
    (local_pkg / "__init__.py").write_text("x = 1\n", encoding="utf-8")
    src_pkg = root / "src" / "plugins" / "draw"
    src_pkg.mkdir(parents=True)
    (src_pkg / "__init__.py").write_text("x = 1\n", encoding="utf-8")
    monkeypatch.setattr("src.console.webui.plugin_catalog.PROJECT_ROOT", root)
    monkeypatch.setattr(
        "src.foundation.config.repo_settings.read_bootstrap_extra_plugin_dirs",
        lambda: ["local/plugins"],
    )
    from src.console.webui.plugin_catalog import resolve_catalog_plugin_module

    assert resolve_catalog_plugin_module("draw") == "local.plugins.draw"
