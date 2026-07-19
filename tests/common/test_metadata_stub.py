from pathlib import Path

from pallas.core.commands.metadata_stub import parse_plugin_metadata_extra_stub
from pallas.core.limits.metadata import parse_command_limits_stub


def test_parse_command_limits_stub_reads_command_limit_list_rows() -> None:
    init_path = Path("packages/blacklist/__init__.py")
    stub = parse_command_limits_stub(init_path)
    assert stub is not None
    ids = [row.id for row in stub["command_limits"]]
    assert ids == ["blacklist.add", "blacklist.remove", "blacklist.list"]


def test_parse_plugin_metadata_extra_stub_reads_command_perm_list_rows() -> None:
    init_path = Path("packages/help/__init__.py")
    stub = parse_plugin_metadata_extra_stub(init_path)
    assert stub is not None
    perm_ids = [row["id"] for row in stub.get("command_permissions") or []]
    limit_ids = [row["id"] for row in stub.get("command_limits") or []]
    assert "help.help" in perm_ids
    assert "help.plugin_enable" in perm_ids
    assert limit_ids == [
        "help.help",
        "help.plugin_enable",
        "help.plugin_disable",
        "help.plugin_enable_all",
        "help.plugin_disable_all",
    ]


def test_disk_command_limits_without_loaded_plugins(monkeypatch) -> None:
    from pallas.core.limits.schema import _disk_plugin_rows, clear_merged_command_limits_cache

    monkeypatch.setattr("pallas.core.limits.schema.get_loaded_plugins", list)
    clear_merged_command_limits_cache()
    rows = {name: len(decls) for name, _title, decls in _disk_plugin_rows()}
    assert rows.get("blacklist", 0) >= 3
    assert rows.get("help", 0) >= 5
    assert rows.get("request_handler", 0) >= 10
    assert rows.get("draw", 0) >= 1
    assert rows.get("sing", 0) >= 1
    assert rows.get("bot_status", 0) >= 1
