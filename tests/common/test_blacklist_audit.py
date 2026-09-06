from __future__ import annotations

import inspect

import pytest


@pytest.mark.asyncio
async def test_group_blacklist_operations_keep_audit_history(beanie_fixture):
    from pallas.core.foundation.config import GroupConfig

    assert "operator" in inspect.signature(GroupConfig.ban).parameters
    from pallas.core.foundation.db.modules import BlacklistAudit

    group = GroupConfig(7001)
    await group.ban(operator="u:3023094357", reason="手动拉黑群")
    await group.add_blocked_users(
        [123456],
        operator="system:rage",
        reason="持续对 Bot 辱骂/脏话攻击（多次触发静默）",
    )
    await group.unban(operator="webui", reason="WebUI 解除群封禁")

    rows = await BlacklistAudit.find_all().sort("created_at").to_list()
    assert [(row.target_type, row.action, row.operator) for row in rows] == [
        ("group", "ban", "u:3023094357"),
        ("group_user", "ban", "system:rage"),
        ("group", "unban", "webui"),
    ]
    assert rows[1].group_id == 7001
    assert rows[1].target_id == 123456
    assert rows[1].reason == "持续对 Bot 辱骂/脏话攻击（多次触发静默）"


@pytest.mark.asyncio
async def test_console_can_browse_blacklist_audit_rows(beanie_fixture):
    from pallas.core.foundation.db.blacklist_audit import record_blacklist_audit
    from pallas.core.foundation.db.pallas_console_data import list_console_table_rows

    await record_blacklist_audit(
        target_type="group_user",
        target_id=123456,
        group_id=7001,
        action="ban",
        operator="system:rage",
        reason="脏话自动拉黑",
        created_at=100,
    )

    data = await list_console_table_rows("blacklist_audit")
    assert data["total"] == 1
    assert data["rows"] == [
        {
            "id": data["rows"][0]["id"],
            "target_type": "group_user",
            "target_id": 123456,
            "group_id": 7001,
            "action": "ban",
            "operator": "system:rage",
            "reason": "脏话自动拉黑",
            "created_at": 100,
        }
    ]


@pytest.mark.asyncio
async def test_global_user_blacklist_audit_keeps_reason(beanie_fixture):
    from pallas.core.foundation.config import UserConfig
    from pallas.core.foundation.db.modules import BlacklistAudit

    await UserConfig(765432).ban(operator="u:3023094357", reason="命令拉黑用户")

    row = await BlacklistAudit.find_one(BlacklistAudit.target_type == "user")
    assert row is not None
    assert row.target_id == 765432
    assert row.group_id is None
    assert row.reason == "命令拉黑用户"
