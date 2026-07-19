from packages.roulette import __plugin_meta__, parse_roulette_start_command


def test_roulette_metadata_uses_sdk_declarations():
    perms = __plugin_meta__.extra.get("command_permissions") or []
    assert len(perms) == 1
    assert __plugin_meta__.extra.get("reload_policy") == "metadata"


def test_parse_roulette_start_command_default_mode():
    matched, mode = parse_roulette_start_command("牛牛轮盘")
    assert matched is True
    assert mode is None
