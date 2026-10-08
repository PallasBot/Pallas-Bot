from pathlib import Path

import pytest

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


def test_static_plugin_id_fstring_rows_reach_unloaded_limit_consumer(tmp_path) -> None:
    init_path = tmp_path / "__init__.py"
    init_path.write_text(
        """PLUGIN_ID = 'memes'
from pallas.api import command_perm_row, command_limit_row
__plugin_meta__ = PluginMetadata(
    name='Memes',
    extra={
        'command_permissions': [command_perm_row(f'{PLUGIN_ID}.list', 'List', 'member')],
        'command_limits': [command_limit_row(f'{PLUGIN_ID}.list', 3)],
    },
)
""",
        encoding="utf-8",
    )

    stub = parse_plugin_metadata_extra_stub(init_path)

    assert stub["command_permissions"][0]["id"] == "memes.list"
    assert stub["command_limits"][0]["id"] == "memes.list"
    from pallas.core.limits.metadata import parse_command_limits_stub

    limits = parse_command_limits_stub(init_path)
    assert [row.id for row in limits["command_limits"]] == ["memes.list"]


def test_static_rows_reject_unknown_and_rebound_names(tmp_path) -> None:
    init_path = tmp_path / "__init__.py"
    init_path.write_text(
        """PLUGIN_ID = 'memes'
PLUGIN_ID = make_id()
__plugin_meta__ = PluginMetadata(extra={
    'command_permissions': [
        command_perm_row(f'{PLUGIN_ID}.list', 'List', 'member'),
        command_perm_row(f'{UNKNOWN}.bad', 'Bad', 'member'),
    ],
    'command_limits': [
        command_limit_row(f'{PLUGIN_ID}.list', 3),
        command_limit_row(f'{UNKNOWN}.bad', 3),
    ],
})
""",
        encoding="utf-8",
    )

    stub = parse_plugin_metadata_extra_stub(init_path)

    assert all(not row["id"] for row in stub["command_permissions"])
    assert all(not row["id"] for row in stub["command_limits"])


def test_literal_dict_rows_and_helper_rows_remain_supported(tmp_path) -> None:
    init_path = tmp_path / "__init__.py"
    init_path.write_text(
        """__plugin_meta__ = PluginMetadata(extra={
    'command_permissions': [{'id': 'demo.list', 'label': 'List', 'default': 'member'}],
    'command_limits': [command_limit_row('demo.list', 3)],
})
""",
        encoding="utf-8",
    )

    stub = parse_plugin_metadata_extra_stub(init_path)

    assert stub["command_permissions"] == [{"id": "demo.list", "label": "List", "default": "member"}]
    assert stub["command_limits"] == [{"id": "demo.list", "cd_sec": 3}]


def test_static_string_name_invalidation_and_whitespace(tmp_path) -> None:
    init_path = tmp_path / "__init__.py"
    init_path.write_text(
        """PLUGIN_ID = ' demo '
if flag:
    PLUGIN_ID = 'other'
__plugin_meta__ = PluginMetadata(extra={
    'command_permissions': [
        command_perm_row(f'{PLUGIN_ID}.x', 'X', 'member'),
        {'id': f'{PLUGIN_ID}.dict', 'label': 'Dict', 'default': 'member'},
    ],
})
""",
        encoding="utf-8",
    )

    stub = parse_plugin_metadata_extra_stub(init_path)

    assert [row.get("id", "") for row in stub["command_permissions"]] == ["", ""]


@pytest.mark.parametrize(
    "binding",
    [
        "import other as PLUGIN_ID",
        "from other import value as PLUGIN_ID",
        "def PLUGIN_ID(): pass",
        "del PLUGIN_ID",
    ],
)
def test_nonliteral_top_level_bindings_invalidate_static_names(tmp_path, binding) -> None:
    init_path = tmp_path / "__init__.py"
    init_path.write_text(
        f"""PLUGIN_ID = 'demo'
{binding}
__plugin_meta__ = PluginMetadata(extra={{
    'command_permissions': [command_perm_row(f'{{PLUGIN_ID}}.x', 'X', 'member')],
}})
""",
        encoding="utf-8",
    )

    stub = parse_plugin_metadata_extra_stub(init_path)

    assert stub["command_permissions"][0]["id"] == ""


@pytest.mark.parametrize("binding", ["def PLUGIN_ID(): pass", "class PLUGIN_ID: pass"])
def test_nested_definition_invalidates_static_names(tmp_path, binding) -> None:
    init_path = tmp_path / "__init__.py"
    init_path.write_text(
        f"""PLUGIN_ID = 'demo'
if flag:
    {binding}
__plugin_meta__ = PluginMetadata(extra={{
    'command_permissions': [command_perm_row(f'{{PLUGIN_ID}}.x', 'X', 'member')],
}})
""",
        encoding="utf-8",
    )

    stub = parse_plugin_metadata_extra_stub(init_path)

    assert stub["command_permissions"][0]["id"] == ""


def test_named_expression_rebinding_invalidates_static_names(tmp_path) -> None:
    init_path = tmp_path / "__init__.py"
    init_path.write_text(
        """PLUGIN_ID = 'demo'
OTHER = (PLUGIN_ID := dynamic())
__plugin_meta__ = PluginMetadata(extra={
    'command_permissions': [command_perm_row(f'{PLUGIN_ID}.x', 'X', 'member')],
})
""",
        encoding="utf-8",
    )

    stub = parse_plugin_metadata_extra_stub(init_path)

    assert stub["command_permissions"][0]["id"] == ""


def test_permission_stub_consumer_gets_static_fstring_id(tmp_path) -> None:
    from pallas.core.perm.metadata import parse_command_permissions_stub

    init_path = tmp_path / "__init__.py"
    init_path.write_text(
        """PLUGIN_ID = 'demo'
__plugin_meta__ = PluginMetadata(extra={
    'command_permissions': [command_perm_row(f'{PLUGIN_ID}.x', 'X', 'member')],
})
""",
        encoding="utf-8",
    )

    stub = parse_command_permissions_stub(init_path)

    assert [row.id for row in stub["command_permissions"]] == ["demo.x"]


def test_static_fstring_preserves_component_whitespace_then_strips_field(tmp_path) -> None:
    init_path = tmp_path / "__init__.py"
    init_path.write_text(
        """PLUGIN_ID = ' demo '
__plugin_meta__ = PluginMetadata(extra={
    'command_permissions': [
        command_perm_row(f'{PLUGIN_ID}.x', 'X', 'member'),
        {'id': f'{PLUGIN_ID}.dict', 'label': 'Dict', 'default': 'member'},
    ],
})
""",
        encoding="utf-8",
    )

    stub = parse_plugin_metadata_extra_stub(init_path)

    assert [row["id"] for row in stub["command_permissions"]] == ["demo .x", "demo .dict"]
