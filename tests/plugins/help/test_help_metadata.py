from packages.help import __plugin_meta__


def test_help_metadata_uses_sdk_declarations():
    perms = __plugin_meta__.extra.get("command_permissions") or []
    limits = __plugin_meta__.extra.get("command_limits") or []
    storage = __plugin_meta__.extra.get("plugin_storage") or []
    assert len(perms) == 5
    assert limits[0]["id"] == "help.help"
    assert __plugin_meta__.extra.get("reload_policy") == "metadata"
    assert {row["key"] for row in storage} == {"hidden_plugins", "global_disabled_plugins"}
