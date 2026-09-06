from __future__ import annotations

from unittest.mock import AsyncMock

import pytest


@pytest.mark.asyncio
async def test_group_config_api_records_blacklist_changes(beanie_fixture, monkeypatch):
    from packages.pb_webui.instances_configs_api import _GroupConfigPatch, _apply_group_config_patch
    from pallas.core.foundation.db.modules import BlacklistAudit

    monkeypatch.setattr("packages.blacklist.apply_group_banned_change", AsyncMock())
    monkeypatch.setattr("packages.blacklist.apply_group_blocked_users_change", AsyncMock())

    await _apply_group_config_patch(
        7002,
        _GroupConfigPatch(banned=True, blocked_user_ids=[123, 456]),
    )
    await _apply_group_config_patch(
        7002,
        _GroupConfigPatch(banned=False, blocked_user_ids=[456]),
    )

    rows = await BlacklistAudit.find_all().to_list()
    assert {(row.target_type, row.target_id, row.action) for row in rows} == {
        ("group", 7002, "ban"),
        ("group", 7002, "unban"),
        ("group_user", 123, "ban"),
        ("group_user", 123, "unban"),
        ("group_user", 456, "ban"),
    }
    assert all(row.operator == "webui" for row in rows)


@pytest.mark.asyncio
async def test_legacy_db_table_row_api_records_blacklist_changes(beanie_fixture, monkeypatch):
    from packages.pb_webui.db_api import _upsert_db_table_row
    from pallas.core.foundation.db.modules import BlacklistAudit

    monkeypatch.setattr("packages.blacklist.apply_group_banned_change", AsyncMock())
    monkeypatch.setattr("packages.blacklist.apply_group_blocked_users_change", AsyncMock())

    await _upsert_db_table_row("group_config", 7003, {"banned": True, "blocked_user_ids": [789]})

    rows = await BlacklistAudit.find_all().to_list()
    assert {(row.target_type, row.target_id, row.action, row.reason) for row in rows} == {
        ("group", 7003, "ban", "WebUI 修改群封禁"),
        ("group_user", 789, "ban", "WebUI 修改群内屏蔽名单"),
    }
