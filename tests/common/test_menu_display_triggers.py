from pallas.core.perm.menu_display import (
    enrich_commands_with_menu_triggers,
    trigger_conditions_by_command_id,
)


def test_trigger_conditions_by_command_id_merges_menu_bindings() -> None:
    menu_items = [
        {
            "trigger_condition": "牛牛黑名单 / 牛牛查看黑名单",
            "command_permission": "blacklist.list",
        },
        {
            "trigger_condition": "牛牛拉黑 / 牛牛屏蔽 / 牛牛解禁 + QQ 或 @",
            "command_permissions": ["blacklist.add", "blacklist.remove"],
        },
        {
            "trigger_condition": "牛牛拉黑群 / 牛牛屏蔽群 / 牛牛解禁群 + 群号",
            "command_permissions": ["blacklist.add", "blacklist.remove"],
        },
    ]
    mapping = trigger_conditions_by_command_id(menu_items)
    assert mapping["blacklist.list"] == ["牛牛黑名单 / 牛牛查看黑名单"]
    assert mapping["blacklist.add"] == [
        "牛牛拉黑 / 牛牛屏蔽 / 牛牛解禁 + QQ 或 @",
        "牛牛拉黑群 / 牛牛屏蔽群 / 牛牛解禁群 + 群号",
    ]


def test_enrich_commands_with_menu_triggers_adds_field() -> None:
    commands = [
        {"command_id": "blacklist.add", "label": "牛牛拉黑 / 牛牛屏蔽 / 牛牛拉黑群"},
        {"command_id": "blacklist.list", "label": "牛牛黑名单 / 牛牛查看黑名单"},
    ]
    menu_items = [
        {
            "trigger_condition": "牛牛黑名单 / 牛牛查看黑名单",
            "command_permission": "blacklist.list",
        },
        {
            "trigger_condition": "牛牛拉黑 / 牛牛屏蔽 + QQ 或 @",
            "command_permission": "blacklist.add",
        },
    ]
    enriched = enrich_commands_with_menu_triggers(commands, menu_items)
    by_id = {row["command_id"]: row for row in enriched}
    assert by_id["blacklist.list"]["trigger_condition"] == "牛牛黑名单 / 牛牛查看黑名单"
    assert by_id["blacklist.add"]["trigger_condition"] == "牛牛拉黑 / 牛牛屏蔽 + QQ 或 @"
    assert (
        "trigger_condition"
        not in enrich_commands_with_menu_triggers(
            [{"command_id": "x.y", "label": "示例"}],
            [],
        )[0]
    )
