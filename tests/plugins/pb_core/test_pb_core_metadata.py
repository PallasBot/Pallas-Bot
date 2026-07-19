from packages.pb_core import __plugin_meta__
from pallas.core.commands import missing_command_declarations


def test_pb_core_metadata_declares_all_commands():
    command_ids = {
        "pb_core.status",
        "pb_core.console",
        "pb_core.plugins",
        "pb_core.update_check",
        "pb_core.restart",
        "pb_core.add_bot_admin",
    }
    assert missing_command_declarations(__plugin_meta__.extra, command_ids=command_ids) == []


def test_pb_core_help_name():
    assert __plugin_meta__.name == "牛牛核心"


def test_pb_core_status_menu_is_superuser_only_help():
    menu = __plugin_meta__.extra.get("menu_data") or []
    status_item = next(item for item in menu if item.get("command_permission") == "pb_core.status")
    assert status_item.get("help_audience") == "superuser"


def test_pb_core_menu_items_all_have_trigger_condition():
    # 每条 menu 都要带 trigger_condition，否则帮助图「怎么说」列会回退成占位符。
    menu = __plugin_meta__.extra.get("menu_data") or []
    assert len(menu) == 6
    for item in menu:
        assert item.get("trigger_condition"), item.get("func")


def test_pb_core_plugin_is_superuser_only_help():
    assert __plugin_meta__.extra.get("help_audience") == "superuser"
