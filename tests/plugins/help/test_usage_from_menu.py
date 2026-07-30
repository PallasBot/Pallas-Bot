from packages.help.plugin_detail_data import usage_text_from_menu_items


def test_usage_text_from_menu_items_matches_triggers():
    text = usage_text_from_menu_items(
        [
            {
                "func": "运行状态",
                "trigger_condition": "#pallas",
                "brief_des": "群内/私聊发 #pallas，查看进程与分片信息",
            },
            {
                "func": "牛牛更新",
                "trigger_condition": "牛牛更新",
                "brief_des": "检查；应用|全部",
                "help_audience": "superuser",
            },
        ]
    )
    assert "#pallas" in text
    assert "牛牛更新" in text
    assert "1." in text and "2." in text
