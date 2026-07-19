from packages.repeater import __plugin_meta__


def test_repeater_metadata_uses_sdk_permissions():
    perms = __plugin_meta__.extra.get("command_permissions") or []
    ids = {row["id"] for row in perms}
    assert ids == {"repeater.ban", "repeater.ban_latest"}
