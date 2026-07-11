"""ACL 启动期迁移：从老列 (BotConfig.admins / UserConfig.banned / GroupConfig.banned /
GroupConfig.blocked_user_ids) 派生 ACL 行与 admin_members 行。幂等。
"""

from __future__ import annotations

from typing import Any

from pallas.core.foundation.db import (
    ensure_backend_registered,
    make_acl_repository,
    make_admin_repository,
    make_bot_config_repository,
)

# run-once step names
_MIGRATE_ADMINS_STEP = "acl.migrate_bot_admins_to_admin_members"
_DERIVE_LEGACY_BANS_STEP = "acl.derive_acl_from_legacy_bans"


async def migrate_bot_admins_to_admin_members_once() -> dict[str, int]:
    """把 BotConfig.admins 各项转到 admin_members 表（scope="bot"）。幂等。"""
    ensure_backend_registered()
    repo = make_admin_repository()
    acl_repo = make_acl_repository()
    if await acl_repo.has_run_step(_MIGRATE_ADMINS_STEP):
        return {"already_run": 1, "migrated": 0}
    bot_config_repo = make_bot_config_repository()
    bot_ids: list[int] = []
    try:
        row = await bot_config_repo.get(0, ignore_cache=True)
        if row is not None:
            bot_ids.append(0)
    except Exception:
        pass
    try:
        from pallas.core.foundation.db.modules import BotConfigModule

        cursor = BotConfigModule.find_all()
        async for doc in cursor:
            try:
                bot_ids.append(int(doc.account))
            except Exception:
                continue
    except Exception:
        pass

    migrated = 0
    for bot_id in bot_ids:
        doc = await bot_config_repo.get(bot_id, ignore_cache=True)
        if doc is None:
            continue
        for uid in list(doc.admins or []):
            try:
                u = int(uid)
            except Exception:
                continue
            await repo.upsert_member(user_id=u, scope="bot", bot_id=int(bot_id))
            migrated += 1
    await acl_repo.mark_run_step(_MIGRATE_ADMINS_STEP)
    return {"migrated": migrated, "bots_scanned": len(bot_ids)}


async def derive_acl_from_legacy() -> dict[str, int]:
    """从 UserConfig.banned / GroupConfig.banned / GroupConfig.blocked_user_ids 派生 ACL 行。幂等。"""
    ensure_backend_registered()
    acl_repo = make_acl_repository()
    if await acl_repo.has_run_step(_DERIVE_LEGACY_BANS_STEP):
        return {"already_run": 1}
    counts = {"user_banned": 0, "group_banned": 0, "group_blocked_users": 0}

    try:
        from pallas.core.foundation.db.modules import UserConfigModule

        async for doc in UserConfigModule.find(UserConfigModule.banned == True):  # noqa: E712
            uid = int(getattr(doc, "user_id", 0))
            if not uid:
                continue
            await acl_repo.upsert_rule(
                role="用户",
                subject=f"u:{uid}",
                action="event.receive",
                target_scope="全局",
                target="*",
                effect="deny",
                priority=2000,
                source="system",
            )
            counts["user_banned"] += 1
    except Exception:
        pass

    try:
        from pallas.core.foundation.db.modules import GroupConfigModule

        async for doc in GroupConfigModule.find(GroupConfigModule.banned == True):  # noqa: E712
            gid = int(getattr(doc, "group_id", 0))
            if not gid:
                continue
            await acl_repo.upsert_rule(
                role="群",
                subject=f"g:{gid}",
                action="event.receive",
                target_scope="全局",
                target="*",
                effect="deny",
                priority=2000,
                source="system",
            )
            counts["group_banned"] += 1
    except Exception:
        pass

    try:
        from pallas.core.foundation.db.modules import GroupConfigModule

        async for doc in GroupConfigModule.find_all():
            gid = int(getattr(doc, "group_id", 0))
            if not gid:
                continue
            raw = getattr(doc, "blocked_user_ids", None) or []
            for uid in raw:
                try:
                    u = int(uid)
                except Exception:
                    continue
                await acl_repo.upsert_rule(
                    role="用户",
                    subject=f"u:{u}",
                    action="event.receive",
                    target_scope="全局",
                    target=f"group:{gid}",
                    effect="deny",
                    priority=1000,
                    source="system",
                )
                counts["group_blocked_users"] += 1
    except Exception:
        pass

    await acl_repo.mark_run_step(_DERIVE_LEGACY_BANS_STEP)
    return counts


async def run_acl_startup_migrations() -> dict[str, Any]:
    """对外统一入口：bot hub / worker 启动时调用一次。"""
    out: dict[str, Any] = {}
    try:
        out["bot_admins"] = await migrate_bot_admins_to_admin_members_once()
    except Exception as exc:
        out["bot_admins_error"] = str(exc)
    try:
        out["legacy_bans"] = await derive_acl_from_legacy()
    except Exception as exc:
        out["legacy_bans_error"] = str(exc)
    return out
