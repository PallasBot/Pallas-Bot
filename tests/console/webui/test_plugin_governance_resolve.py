from __future__ import annotations

from pallas.console.webui.plugin_governance import (
    find_capability_plugin_row,
    find_catalog_plugin_row,
    governance_row_from_catalog,
)


def test_find_capability_plugin_row_matches_canonical_alias() -> None:
    capabilities = {
        "plugins": [
            {"plugin": "pb_stats", "title": "在线统计", "commands": []},
        ]
    }
    row = find_capability_plugin_row(capabilities, "community_stats")
    assert row is not None
    assert row["plugin"] == "pb_stats"


def test_governance_row_from_catalog_uses_metadata_title() -> None:
    row = governance_row_from_catalog(
        "help",
        {"name": "help", "metadata": {"name": "牛牛帮助"}},
    )
    assert row["plugin"] == "help"
    assert row["title"] == "牛牛帮助"
    assert row["commands"] == []


def test_find_catalog_plugin_row_matches_resolved_id() -> None:
    rows = [{"name": "draw", "resolved_plugin_id": "draw", "nb_plugin_name": "packages.draw"}]
    assert find_catalog_plugin_row(rows, "draw") is not None
