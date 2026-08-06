from packages.llm_chat import __plugin_meta__


def test_llm_status_menu_is_superuser_only_help():
    menu = __plugin_meta__.extra.get("menu_data") or []
    status_item = next(item for item in menu if item.get("command_permission") == "llm_chat.status")
    assert status_item.get("help_audience") == "superuser"


def test_llm_sticker_test_menu_is_superuser_only_help():
    menu = __plugin_meta__.extra.get("menu_data") or []
    items = [item for item in menu if item.get("command_permission") == "llm_chat.sticker_test"]

    assert [item.get("trigger_condition") for item in items] == ["牛牛测试缓存表情", "牛牛测试LLM表情 + 待匹配文本"]
    assert all(item.get("help_audience") == "superuser" for item in items)


def test_llm_chat_plugin_is_user_facing_help():
    audience = str(__plugin_meta__.extra.get("help_audience") or "user").strip().lower()
    assert audience not in {"superuser", "maintainer"}


def test_user_menu_items_cover_chat_clear_and_drunk():
    menu = __plugin_meta__.extra.get("menu_data") or []
    user_items = [
        item
        for item in menu
        if str(item.get("help_audience") or "user").strip().lower() not in {"superuser", "maintainer"}
    ]
    funcs = {item.get("func") for item in user_items}
    assert "智能对话" in funcs
    assert "酒后聊天" in funcs
    assert "清空和牛牛的记录" in funcs
    assert "LLM 状态" not in funcs
    assert "换模型" not in funcs
    assert "卸模型" not in funcs


def test_drunk_chat_menu_item_present():
    menu = __plugin_meta__.extra.get("menu_data") or []
    drunk = next(item for item in menu if item.get("func") == "酒后聊天")
    assert drunk.get("command_permission") == "llm_chat.chat"
    assert "醉酒" in str(drunk.get("trigger_condition") or "")
