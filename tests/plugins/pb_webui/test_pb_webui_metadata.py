from packages.pb_webui import __plugin_meta__


def test_pb_webui_metadata():
    assert __plugin_meta__.name == "Web 控制台"
    assert __plugin_meta__.extra.get("help_audience") == "superuser"
    assert __plugin_meta__.extra.get("reload_policy") == "metadata"
    menu = __plugin_meta__.extra.get("menu_data") or []
    assert len(menu) == 2
