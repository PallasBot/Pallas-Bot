"""ACL 启动迁移测试：从 legacy 列派生 acl_rules / admin_members。"""

import pytest

from pallas.core.foundation.config import GroupConfig, UserConfig
from pallas.core.foundation.db import make_acl_repository, make_admin_repository


@pytest.mark.asyncio
async def test_derive_acl_from_legacy_mirrors_bans(beanie_fixture):
    from pallas.core.perm.migration import derive_acl_from_legacy

    uid = 770_001
    gid = 770_002
    blocked = 770_003
    await UserConfig(uid).ban()
    await GroupConfig(gid).ban()
    await GroupConfig(gid).add_blocked_users([blocked])

    counts = await derive_acl_from_legacy()
    assert counts["user_banned"] == 1
    assert counts["group_banned"] == 1
    assert counts["group_blocked_users"] == 1

    repo = make_acl_repository()
    rules = await repo.list_all()
    by_sig = {(r.role, r.subject, r.action, r.target_scope, r.target): r for r in rules}
    assert ("用户", f"u:{uid}", "event.receive", "全局", "*") in by_sig
    assert ("群", f"g:{gid}", "event.receive", "全局", "group") in by_sig
    assert ("用户", f"u:{blocked}", "event.receive", "全局", f"group:{gid}") in by_sig
    assert by_sig[("用户", f"u:{uid}", "event.receive", "全局", "*")].effect == "deny"
    assert by_sig[("用户", f"u:{uid}", "event.receive", "全局", "*")].priority == 2000
    assert by_sig[("用户", f"u:{blocked}", "event.receive", "全局", f"group:{gid}")].priority == 1000


@pytest.mark.asyncio
async def test_derive_acl_from_legacy_idempotent(beanie_fixture):
    from pallas.core.perm.migration import derive_acl_from_legacy

    uid = 770_011
    await UserConfig(uid).ban()

    first = await derive_acl_from_legacy()
    second = await derive_acl_from_legacy()
    assert first["user_banned"] == 1
    assert second == {"already_run": 1}

    repo = make_acl_repository()
    rules = await repo.list_all()
    assert len(rules) == 1


@pytest.mark.asyncio
async def test_migrate_bot_admins_to_admin_members_once(beanie_fixture):
    from pallas.core.foundation.db import make_bot_config_repository
    from pallas.core.perm.migration import migrate_bot_admins_to_admin_members_once

    bot_id = 770_021
    admin_uid = 770_022
    repo = make_bot_config_repository()
    await repo.get_or_create(bot_id, disabled_plugins=[])
    await repo.upsert_field(bot_id, "admins", [admin_uid])

    result = await migrate_bot_admins_to_admin_members_once()
    assert result["migrated"] == 1

    admin_repo = make_admin_repository()
    uids = await admin_repo.list_admin_user_ids(bot_id=bot_id)
    assert admin_uid in uids

    again = await migrate_bot_admins_to_admin_members_once()
    assert again["already_run"] == 1
