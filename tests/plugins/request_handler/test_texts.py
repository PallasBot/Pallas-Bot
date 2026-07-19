from packages.help.plugin_aliases import aliases_for_plugin
from packages.request_handler.texts import (
    QUICK_APPROVE_ACTIONS,
    build_list_tail,
    build_quick_action_arg_hint,
    build_quick_action_missing_hint,
)


def test_request_handler_help_aliases_include_display_name() -> None:
    aliases = aliases_for_plugin("request_handler")
    assert "申请管理" in aliases
    assert "好友申请" in aliases
    assert "入群申请" in aliases


def test_friend_list_tail_uses_consistent_commands() -> None:
    text = build_list_tail("friend")
    assert "查看好友申请" in text
    assert "同意好友 <QQ号>" in text
    assert "拒绝好友 <QQ号>" in text
    assert "同意所有好友" in text
    assert "牛牛帮助 申请管理" in text


def test_group_list_tail_prefers_application_wording() -> None:
    text = build_list_tail("group")
    assert "查看入群申请" in text
    assert "查看入群邀请" not in text
    assert "同意入群 <群号>" in text
    assert "拒绝所有入群" in text


def test_quick_action_hints_guide_to_explicit_commands() -> None:
    assert QUICK_APPROVE_ACTIONS == ("同意", "拒绝")
    approve_hint = build_quick_action_arg_hint("同意")
    reject_hint = build_quick_action_arg_hint("拒绝")
    assert "同意好友 <QQ号>" in approve_hint
    assert "同意入群 <群号>" in approve_hint
    assert "引用那条提醒" in approve_hint
    assert "拒绝好友 <QQ号>" in reject_hint
    assert "拒绝入群 <群号>" in reject_hint


def test_missing_latest_hint_points_back_to_list_commands() -> None:
    text = build_quick_action_missing_hint("同意")
    assert "没有可直接处理的最新申请提醒" in text
    assert "查看好友申请" in text
    assert "查看入群申请" in text
    assert "同意好友 <QQ号>" in text
