from packages.request_handler import __plugin_meta__


def test_request_handler_metadata_uses_sdk_declarations():
    perms = __plugin_meta__.extra.get("command_permissions") or []
    assert len(perms) == 18
    assert __plugin_meta__.extra.get("reload_policy") == "metadata"
    assert __plugin_meta__.extra.get("disable_scope") == "bot"
