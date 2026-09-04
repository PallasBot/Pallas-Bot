"""BotConfig.admins 与 admin_members 同步测试。"""

import pytest

from pallas.core.foundation.config import sync_bot_admins_to_admin_members
from pallas.core.foundation.db import make_admin_repository, make_bot_config_repository


@pytest.mark.asyncio
async def test_sync_bot_admins_to_admin_members_add_and_remove(beanie_fixture):
    bot_id = 880_001
    admin_a = 880_002
    admin_b = 880_003

    repo = make_bot_config_repository()
    await repo.get_or_create(bot_id, disabled_plugins=[])
    await repo.upsert_field(bot_id, "admins", [admin_a, admin_b])

    await sync_bot_admins_to_admin_members(bot_id, [admin_a, admin_b])
    admin_repo = make_admin_repository()
    uids = await admin_repo.list_admin_user_ids(bot_id=bot_id)
    assert set(uids) == {admin_a, admin_b}

    # 删除 admin_b
    await repo.upsert_field(bot_id, "admins", [admin_a])
    await sync_bot_admins_to_admin_members(bot_id, [admin_a])
    uids = await admin_repo.list_admin_user_ids(bot_id=bot_id)
    assert set(uids) == {admin_a}


@pytest.mark.asyncio
async def test_sync_bot_admins_skips_bot_self(beanie_fixture):
    bot_id = 880_011
    await sync_bot_admins_to_admin_members(bot_id, [bot_id, 880_012])
    admin_repo = make_admin_repository()
    uids = await admin_repo.list_admin_user_ids(bot_id=bot_id)
    assert set(uids) == {880_012}


@pytest.mark.asyncio
async def test_sync_bot_admins_raises_when_query_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    """查询 admin_members 失败时抛错，不静默当空集合，避免旧号主残留。"""

    class _FailingRepo:
        async def list_members(self, **kwargs):
            raise RuntimeError("db down")

    monkeypatch.setattr(
        "pallas.core.foundation.db.make_admin_repository",
        lambda: _FailingRepo(),
    )
    with pytest.raises(RuntimeError, match="db down"):
        await sync_bot_admins_to_admin_members(880_021, [880_022])
