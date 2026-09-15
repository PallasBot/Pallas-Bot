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
async def test_prune_orphan_legacy_acl_rules(beanie_fixture):
    from pallas.core.perm.migration import prune_orphan_legacy_acl_rules

    orphan_uid = 770_031
    orphan_gid = 770_032
    kept_uid = 770_033
    governance_uid = 770_034
    repo = make_acl_repository()
    # 孤儿：user/group 配置行已删，ACL deny 残留
    await repo.upsert_rule(
        role="用户",
        subject=f"u:{orphan_uid}",
        action="event.receive",
        target_scope="全局",
        target="*",
        effect="deny",
        priority=2000,
        source="system",
    )
    await repo.upsert_rule(
        role="群",
        subject=f"g:{orphan_gid}",
        action="event.receive",
        target_scope="全局",
        target="group",
        effect="deny",
        priority=2000,
        source="system",
    )
    # 非孤儿：仍被封禁
    await UserConfig(kept_uid).ban()
    await repo.upsert_rule(
        role="用户",
        subject=f"u:{kept_uid}",
        action="event.receive",
        target_scope="全局",
        target="*",
        effect="deny",
        priority=2000,
        source="system",
    )
    # 非 system 来源（治理规则）不应被清
    await repo.upsert_rule(
        role="用户",
        subject=f"u:{governance_uid}",
        action="event.receive",
        target_scope="全局",
        target="*",
        effect="deny",
        priority=1500,
        source="governance",
    )
    # 群内黑名单：孤儿 vs 仍在名单
    live_blocked_gid = 770_035
    live_blocked_uid = 770_036
    await GroupConfig(live_blocked_gid).add_blocked_users([live_blocked_uid])
    await repo.upsert_rule(
        role="用户",
        subject=f"u:{live_blocked_uid}",
        action="event.receive",
        target_scope="全局",
        target=f"group:{live_blocked_gid}",
        effect="deny",
        priority=1000,
        source="system",
    )
    await repo.upsert_rule(
        role="用户",
        subject="u:770_037",
        action="event.receive",
        target_scope="全局",
        target="group:770_038",
        effect="deny",
        priority=1000,
        source="system",
    )

    removed = await prune_orphan_legacy_acl_rules()
    assert removed == 3

    remaining = {(r.subject, r.target, r.source) for r in await repo.list_all()}
    assert remaining == {
        (f"u:{kept_uid}", "*", "system"),
        (f"u:{governance_uid}", "*", "governance"),
        (f"u:{live_blocked_uid}", f"group:{live_blocked_gid}", "system"),
    }


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
