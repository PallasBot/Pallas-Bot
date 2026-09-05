from types import SimpleNamespace

from pallas.core.perm.help_menu import (
    help_say_phrase,
    help_scene_text,
    is_user_help_menu_item,
    is_user_help_plugin,
    iter_plugin_detail_menu,
    iter_user_help_menu,
)


def test_help_say_strips_scene_paren() -> None:
    item = {"trigger_condition": "设置群欢迎（群内）", "trigger_scene": "群内"}
    assert help_say_phrase(item) == "设置群欢迎"


def test_help_scene_explicit() -> None:
    item = {"trigger_method": "on_message", "trigger_scene": "私聊"}
    assert help_scene_text(item) == "私聊"


def test_help_scene_std_method() -> None:
    assert help_scene_text({"trigger_method": "on_cmd"}) == "发命令"
    assert help_scene_text({"trigger_method": "on_message"}) == "发消息"
    assert help_scene_text({"trigger_method": "scheduler"}) == "自动"
    assert help_scene_text({"trigger_method": "on_notice"}) == "自动"


def test_help_scene_chinese_method_keyword() -> None:
    # 自由中文触发文本（社区 PicMenu 约定）：带场景词的归一，其余保持 —
    assert help_scene_text({"trigger_method": "私聊"}) == "私聊"
    assert help_scene_text({"trigger_method": "群聊"}) == "群内"
    assert help_scene_text({"trigger_method": "群内"}) == "群内"
    assert help_scene_text({"trigger_method": "自动签到"}) == "自动"
    assert help_scene_text({"trigger_method": "定时任务"}) == "自动"


def test_help_scene_chinese_non_scene_keeps_placeholder() -> None:
    # 权限/触发方式语义（已绑定用户/超级用户/回复…/无限制）不映射场景
    assert help_scene_text({"trigger_method": "已绑定用户"}) == "—"
    assert help_scene_text({"trigger_method": "超级用户"}) == "—"
    assert help_scene_text({"trigger_method": "回复一条战绩图片消息"}) == "—"
    assert help_scene_text({"trigger_method": "无限制"}) == "—"


def test_help_scene_multi_method_with_chinese() -> None:
    assert help_scene_text({"trigger_method": "私聊/私聊"}) == "私聊"
    assert help_scene_text({"trigger_method": "私聊/群聊"}) == "多种"
    assert help_scene_text({"trigger_method": "on_cmd/on_notice"}) == "多种"


def test_maintainer_filtered_from_user_menu() -> None:
    menu = [
        {"func": "用户功能", "trigger_condition": "牛牛帮助"},
        {"func": "HTTP", "help_audience": "maintainer", "trigger_condition": "/api"},
        {"func": "超管功能", "help_audience": "superuser", "trigger_condition": "牛牛状态"},
    ]
    assert len(list(iter_user_help_menu(menu))) == 1
    assert is_user_help_menu_item(menu[1]) is False
    assert is_user_help_menu_item(menu[2]) is False


def test_maintainer_plugin_extra_excluded_from_user_help() -> None:
    user_plugin = SimpleNamespace(metadata=SimpleNamespace(extra={"help_audience": "user"}))
    maintainer_plugin = SimpleNamespace(metadata=SimpleNamespace(extra={"help_audience": "maintainer"}))
    superuser_plugin = SimpleNamespace(metadata=SimpleNamespace(extra={"help_audience": "superuser"}))
    assert is_user_help_plugin(user_plugin) is True
    assert is_user_help_plugin(maintainer_plugin) is False
    assert is_user_help_plugin(superuser_plugin) is False
    assert is_user_help_plugin(SimpleNamespace(metadata=None)) is True


def test_plugin_detail_menu_shows_all_items_for_superuser_plugin() -> None:
    # 超管专属插件详情页应展示全部条目（含 help_audience 受限项），
    # 普通插件在普通视图仍按 user 受众过滤；超管私聊（show_ignored）展示全部。
    menu = [
        {"func": "用户功能", "trigger_condition": "牛牛帮助"},
        {"func": "超管功能", "help_audience": "superuser", "trigger_condition": "牛牛状态"},
    ]
    superuser_plugin = SimpleNamespace(metadata=SimpleNamespace(extra={"help_audience": "superuser"}))
    user_plugin = SimpleNamespace(metadata=SimpleNamespace(extra={"help_audience": "user"}))

    assert [i["func"] for i in iter_plugin_detail_menu(superuser_plugin, menu)] == ["用户功能", "超管功能"]
    assert [i["func"] for i in iter_plugin_detail_menu(user_plugin, menu)] == ["用户功能"]
    assert [i["func"] for i in iter_plugin_detail_menu(user_plugin, menu, show_ignored=True)] == [
        "用户功能",
        "超管功能",
    ]
