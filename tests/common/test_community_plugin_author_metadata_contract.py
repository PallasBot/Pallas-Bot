from pallas.console.webui.community_plugin_author import parse_plugin_metadata_contract


def test_contract_resolves_static_fstring_permission_and_limit_ids(tmp_path):
    init_path = tmp_path / "__init__.py"
    init_path.write_text(
        """PLUGIN_ID: str = 'memes'
__plugin_meta__ = PluginMetadata(
    name='Memes',
    extra={
        'command_permissions': [command_perm_row(f'{PLUGIN_ID}.list', 'List', 'member')],
        'command_limits': [command_limit_row(f'{PLUGIN_ID}.list', 3)],
        'menu_data': [{'command_permission': 'memes.list'}],
    },
)
""",
        encoding="utf-8",
    )

    contract = parse_plugin_metadata_contract(init_path)

    assert [row["id"] for row in contract["command_permissions"]] == ["memes.list"]
    assert [row["id"] for row in contract["command_limits"]] == ["memes.list"]


def test_contract_does_not_execute_or_guess_dynamic_ids(tmp_path):
    marker = tmp_path / "executed"
    init_path = tmp_path / "__init__.py"
    init_path.write_text(
        f"""PLUGIN_ID = 'memes'
__plugin_meta__ = PluginMetadata(extra={{
    'command_permissions': [
        command_perm_row(f'{{PLUGIN_ID}}.list', 'List', 'member'),
        command_perm_row(f'{{UNKNOWN}}.bad', 'Bad', 'member'),
    ],
    'command_limits': [
        command_limit_row(f'{{PLUGIN_ID}}.list', 3),
        command_limit_row(__import__('pathlib').Path({str(marker)!r}).touch() or 'bad', 3),
    ],
}})
PLUGIN_ID = make_id()
""",
        encoding="utf-8",
    )

    contract = parse_plugin_metadata_contract(init_path)

    assert not marker.exists()
    assert [row["id"] for row in contract["command_permissions"]] == ["memes.list", ""]
    assert [row["id"] for row in contract["command_limits"]] == ["memes.list", ""]
