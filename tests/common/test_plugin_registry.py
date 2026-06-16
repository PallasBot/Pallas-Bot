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
    assert party["priority"] == "P1"
    assert party["install_cli"] == "uv sync --extra plugins-party"
    assert party["webui_install"] is False


def test_build_official_extension_rows_marks_bundled_duel():
    rows = build_official_extension_rows()
    duel = next(r for r in rows if r["package"] == "pallas-plugin-duel")
    assert "duel" in duel["bundled_plugin_ids"]
    assert duel["status"] == "bundled"


def test_official_extension_for_plugin():
    row = official_extension_for_plugin("draw")
    assert row is not None
    assert row["package"] == "pallas-plugin-draw"
