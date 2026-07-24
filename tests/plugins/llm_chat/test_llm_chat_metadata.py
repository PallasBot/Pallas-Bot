from packages.llm_chat import __plugin_meta__


def test_llm_status_menu_is_superuser_only_help():
    menu = __plugin_meta__.extra.get("menu_data") or []
    status_item = next(item for item in menu if item.get("command_permission") == "llm_chat.status")
    assert status_item.get("help_audience") == "superuser"


def test_llm_chat_plugin_is_superuser_only_help():
    assert __plugin_meta__.extra.get("help_audience") == "superuser"


def test_drunk_chat_menu_item_present():
    menu = __plugin_meta__.extra.get("menu_data") or []
    drunk = next(item for item in menu if item.get("func") == "酒后聊天")
    assert drunk.get("command_permission") == "llm_chat.chat"
    assert "醉酒" in str(drunk.get("trigger_condition") or "")
