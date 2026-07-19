from packages.greeting import __plugin_meta__


def test_greeting_metadata_uses_sdk_declarations():
    perms = __plugin_meta__.extra.get("command_permissions") or []
    assert len(perms) == 4
    assert __plugin_meta__.extra.get("reload_policy") == "metadata"
