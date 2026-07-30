from packages.pb_core import __plugin_meta__
from pallas.core.commands import missing_command_declarations
from pallas.core.perm.help_menu import is_user_help_menu_item, iter_user_help_menu
from pallas.core.perm.registry import DEFAULT_COMMAND_PERMISSIONS


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


def test_pb_core_status_is_bot_moderator_and_user_help_visible():
    perms = {row["id"]: row["default"] for row in (__plugin_meta__.extra.get("command_permissions") or [])}
    assert perms["pb_core.status"] == "bot_moderator"
    assert DEFAULT_COMMAND_PERMISSIONS["pb_core.status"] == "bot_moderator"

    menu = __plugin_meta__.extra.get("menu_data") or []
    status_item = next(item for item in menu if item.get("command_permission") == "pb_core.status")
    assert is_user_help_menu_item(status_item) is True
    assert status_item.get("func") == "运行状态"
    assert status_item.get("trigger_condition") == "#pallas"
    assert [i["func"] for i in iter_user_help_menu(menu)] == ["运行状态"]
    assert len(menu) == 6
    for item in menu:
        assert item.get("trigger_condition"), item.get("func")


def test_pb_core_sensitive_commands_remain_superuser_help():
    menu = __plugin_meta__.extra.get("menu_data") or []
    for item in menu:
        if item.get("command_permission") == "pb_core.status":
            continue
        assert item.get("help_audience") == "superuser", item.get("func")


def test_pb_core_usage_only_lists_user_facing_status():
    assert "#pallas" in __plugin_meta__.usage
    assert "牛牛重启" not in __plugin_meta__.usage
    assert "牛牛更新" not in __plugin_meta__.usage
    # 勿与扩展插件 bot_status「牛牛状态」撞名
    assert "牛牛状态" not in __plugin_meta__.usage


def test_pb_core_plugin_is_user_help_visible():
    from types import SimpleNamespace

    from pallas.core.perm.help_menu import is_user_help_plugin, iter_plugin_detail_menu

    assert is_user_help_plugin(SimpleNamespace(metadata=__plugin_meta__)) is True
    assert (__plugin_meta__.extra or {}).get("help_audience") not in {"superuser", "maintainer"}

    plugin = SimpleNamespace(metadata=__plugin_meta__)
    menu = __plugin_meta__.extra.get("menu_data") or []
    assert [i["func"] for i in iter_plugin_detail_menu(plugin, menu)] == ["运行状态"]
    funcs = [i["func"] for i in iter_plugin_detail_menu(plugin, menu, show_ignored=True)]
    assert "运行状态" in funcs
    assert "牛牛更新" in funcs
    assert "牛牛重启" in funcs


def test_pb_core_menu_briefs_include_examples():
    menu = {item["func"]: item for item in (__plugin_meta__.extra.get("menu_data") or [])}
    assert "#pallas" in str(menu["运行状态"].get("brief_des") or "")
    assert "应用" in str(menu["牛牛更新"].get("brief_des") or "")
    assert "帮助" in str(menu["牛牛更新"].get("detail_des") or "")
    assert len(str(menu["牛牛更新"].get("detail_des") or "")) < 120
    assert "号主QQ" in str(menu["牛牛添加号主"].get("brief_des") or "")
