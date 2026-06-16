from src.console.webui.plugin_registry import (
    build_official_extension_rows,
    official_extension_for_plugin,
)
from src.platform.bot_runtime.plugin_matrix import uv_extra_for_package, uv_extra_for_plugin


def test_uv_extra_for_plugin_duel():
    assert uv_extra_for_plugin("duel") == "plugins-duel"
    assert uv_extra_for_package("pallas-plugin-party") == "plugins-party"


def test_build_official_extension_rows_groups_party():
    rows = build_official_extension_rows()
    party = next(r for r in rows if r["package"] == "pallas-plugin-party")
    assert set(party["plugin_ids"]) == {"drink", "roulette"}
    assert party["uv_extra"] == "plugins-party"
    assert party["install_cli"] == "uv sync --extra plugins-party"
    assert party["webui_install"] is True
    assert isinstance(party["can_install"], bool)
    assert isinstance(party["restart_available"], bool)


def test_build_official_extension_rows_marks_bundled_duel():
    rows = build_official_extension_rows()
    duel = next(r for r in rows if r["package"] == "pallas-plugin-duel")
    assert "duel" in duel["bundled_plugin_ids"]
    assert duel["status"] in ("bundled", "installed")
    assert isinstance(duel["installed"], bool)
    assert duel["repository_url"] == "https://github.com/TogetsuDo/pallas-plugin-duel"


def test_build_official_extension_rows_p0_repo_urls():
    rows = build_official_extension_rows()
    by_pkg = {r["package"]: r["repository_url"] for r in rows}
    assert by_pkg["pallas-plugin-protocol"] == "https://github.com/TogetsuDo/pallas-plugin-protocol"
    assert by_pkg["pallas-plugin-maa"] == "https://github.com/TogetsuDo/pallas-plugin-maa"
    assert by_pkg["pallas-plugin-who-is-spy"] == "https://github.com/TogetsuDo/pallas-plugin-who-is-spy"
    assert by_pkg.get("pallas-plugin-draw") == "https://github.com/TogetsuDo/pallas-plugin-draw"
    assert by_pkg.get("pallas-plugin-dream") == "https://github.com/TogetsuDo/pallas-plugin-dream"
    assert by_pkg.get("pallas-plugin-social") == "https://github.com/TogetsuDo/pallas-plugin-social"
    assert by_pkg.get("pallas-plugin-llm-chat") == "https://github.com/TogetsuDo/pallas-plugin-llm-chat"


def test_official_extension_for_plugin():
    row = official_extension_for_plugin("draw")
    assert row is not None
    assert row["package"] == "pallas-plugin-draw"
