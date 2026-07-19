from packages.pb_stats import __plugin_meta__


def test_pb_stats_metadata():
    assert __plugin_meta__.name == "在线统计"
    assert __plugin_meta__.extra.get("help_audience") == "superuser"
    menu = __plugin_meta__.extra.get("menu_data") or []
    assert len(menu) == 1
    assert menu[0]["func"] == "在线统计上报"
