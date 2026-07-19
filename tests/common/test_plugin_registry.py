from pallas.console.webui.plugin_registry import (
    build_official_extension_rows,
    official_extension_for_plugin,
)
from pallas.core.platform.bot_runtime.plugin_matrix import uv_extra_for_plugin


def test_uv_extra_for_plugin_duel():
    assert uv_extra_for_plugin("duel") == "plugins-duel"


def test_build_official_extension_rows_excludes_core_social_party():
    rows = build_official_extension_rows()
    packages = {r["package"] for r in rows}
    assert "pallas-plugin-party" not in packages
    assert "pallas-plugin-social" not in packages
    assert official_extension_for_plugin("roulette") is None
    assert official_extension_for_plugin("greeting") is None
    assert official_extension_for_plugin("take_name") is None
    assert official_extension_for_plugin("llm_chat") is None


def test_build_official_extension_rows_marks_bundled_duel():
    rows = build_official_extension_rows()
    duel = next(r for r in rows if r["package"] == "pallas-plugin-duel")
    assert isinstance(duel["bundled_plugin_ids"], list)
    assert duel["status"] in ("bundled", "bundled_active", "installed", "pip_installed", "external")
    assert isinstance(duel["installed"], bool)
    assert duel["repository_url"] == "https://github.com/TogetsuDo/pallas-plugin-duel"
    assert duel["install_cli"] == "uv run pallas ext install pallas-plugin-duel"
    assert duel["activation_policy"] == "workers-restart"


def test_build_official_extension_rows_include_visuals():
    rows = build_official_extension_rows()
    duel = next(r for r in rows if r["package"] == "pallas-plugin-duel")
    assert duel["icon"]
    assert "pallas-plugin-duel" in duel["icon"]
    assert duel["cover"]
    assert "pallas-plugin-duel" in duel["cover"] or "brand-avatar" in duel["cover"]
    assert duel["description"] == "泰拉风味多幕决斗，带剧情事件、抢答和八角笼玩法。"
    assert duel["display_name"] == "牛牛决斗"
    assert duel["avatar"] is None


def test_build_official_extension_rows_ai_media_cover():
    rows = build_official_extension_rows()
    ai = next(r for r in rows if r["package"] == "pallas-plugin-ai-media")
    assert ai["cover"]
    assert ai["cover"] in (
        "https://raw.githubusercontent.com/TogetsuDo/pallas-plugin-ai-media/main/assets/brand-avatar.png",
        "/pallas/store-assets/cover/official-pallas-plugin-ai-media.png",
    )


def test_build_official_extension_rows_prefers_cached_asset_urls(monkeypatch):
    def fake_apply(kind, rows):
        assert kind == "official"
        return [
            {**row, "cover": "/pallas/store-assets/cover/official-draw.webp"}
            if row["package"] == "pallas-plugin-draw"
            else row
            for row in rows
        ]

    monkeypatch.setattr("pallas.console.webui.plugin_store_assets.apply_asset_snapshot_to_rows", fake_apply)

    rows = build_official_extension_rows()
    draw = next(r for r in rows if r["package"] == "pallas-plugin-draw")
    assert draw["cover"] == "/pallas/store-assets/cover/official-draw.webp"


def test_build_official_extension_rows_p0_repo_urls():
    rows = build_official_extension_rows()
    by_pkg = {r["package"]: r["repository_url"] for r in rows}
    assert by_pkg["pallas-plugin-protocol"] == "https://github.com/TogetsuDo/pallas-plugin-protocol"
    assert by_pkg["pallas-plugin-maa"] == "https://github.com/TogetsuDo/pallas-plugin-maa"
    assert by_pkg["pallas-plugin-who-is-spy"] == "https://github.com/TogetsuDo/pallas-plugin-who-is-spy"
    assert by_pkg.get("pallas-plugin-draw") == "https://github.com/TogetsuDo/pallas-plugin-draw"
    assert by_pkg.get("pallas-plugin-dream") == "https://github.com/TogetsuDo/pallas-plugin-dream"
    assert "pallas-plugin-llm-chat" not in by_pkg


def test_official_extension_for_plugin():
    row = official_extension_for_plugin("draw")
    assert row is not None
    assert row["package"] == "pallas-plugin-draw"
    assert row["activation_policy"] == "hot-reloadable"


def test_build_official_extension_rows_marks_loaded_pip_module_as_installed(monkeypatch):
    class FakeLoadedPlugin:
        name = "pallas_plugin_duel"
        module = type("Mod", (), {"__name__": "pallas_plugin_duel"})()
        metadata = None

    monkeypatch.setattr("nonebot.get_loaded_plugins", lambda: [FakeLoadedPlugin()])
    monkeypatch.setattr(
        "pallas.console.webui.plugin_registry.pip_package_installed",
        lambda package: package == "pallas-plugin-duel",
    )

    rows = build_official_extension_rows()
    duel = next(r for r in rows if r["package"] == "pallas-plugin-duel")
    assert duel["installed"] is True
    assert duel["status"] == "installed"
    assert "duel" in duel["loaded_plugin_ids"]


def test_build_official_extension_rows_includes_reload_policy_from_loaded_metadata(monkeypatch):
    class FakeLoadedPlugin:
        name = "draw"
        module = type("Mod", (), {"__name__": "pallas_plugin_draw"})()
        metadata = type("Meta", (), {"extra": {"reload_policy": "metadata"}})()

    monkeypatch.setattr("nonebot.get_loaded_plugins", lambda: [FakeLoadedPlugin()])
    monkeypatch.setattr(
        "pallas.console.webui.plugin_registry.pip_package_installed",
        lambda package: package == "pallas-plugin-draw",
    )

    rows = build_official_extension_rows()
    draw = next(r for r in rows if r["package"] == "pallas-plugin-draw")
    assert draw["reload_policy"] == "metadata"
