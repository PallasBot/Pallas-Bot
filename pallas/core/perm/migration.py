"""ACL 启动期迁移：从老列 (BotConfig.admins / UserConfig.banned / GroupConfig.banned /
GroupConfig.blocked_user_ids) 派生 ACL 行与 admin_members 行。幂等。
"""

from __future__ import annotations

from typing import Any

from nonebot import logger

from pallas.core.foundation.db import (
    ensure_backend_registered,
    make_acl_repository,
    make_admin_repository,
    make_bot_config_repository,
    make_group_config_repository,
    make_user_config_repository,
)
from pallas.core.perm.acl import ACL_TARGET_GROUP_BAN, clear_acl_cache, group_block_target

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
        for doc in await bot_config_repo.list_all():
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
        user_repo = make_user_config_repository()
        for doc in await user_repo.list_all():
            if not bool(getattr(doc, "banned", False)):
                continue
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
        group_repo = make_group_config_repository()
        for doc in await group_repo.list_all():
            gid = int(getattr(doc, "group_id", 0))
            if not gid:
                continue
            if bool(getattr(doc, "banned", False)):
                await acl_repo.upsert_rule(
                    role="群",
                    subject=f"g:{gid}",
                    action="event.receive",
                    target_scope="全局",
                    target=ACL_TARGET_GROUP_BAN,
                    effect="deny",
                    priority=2000,
                    source="system",
                )
                counts["group_banned"] += 1
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
                    target=group_block_target(gid),
                    effect="deny",
                    priority=1000,
                    source="system",
                )
                counts["group_blocked_users"] += 1
    except Exception:
        pass

    await acl_repo.mark_run_step(_DERIVE_LEGACY_BANS_STEP)
    return counts


async def prune_orphan_legacy_acl_rules() -> int:
    """清掉 legacy 已无对应记录的 system 封禁规则。

    早期删除 user_config / group_config 行时不会同步撤 ACL（见 migration 由来），
    留下 subject 已无 banned=true 配置行的 deny，且 target='*' 会命中所有群与私聊。
    这里按行反查，删掉这类孤儿。只处理 source='system' 的封禁签名，
    不碰 WebUI 手写的规则与插件治理规则（source='governance'）。
    """
    acl_repo = make_acl_repository()
    removed = 0
    try:
        groups = await make_group_config_repository().list_all()
    except Exception:
        logger.exception("ACL orphan prune failed to load group configs")
        return 0
    try:
        banned_users = {int(d.user_id) for d in await make_user_config_repository().list_all() if d.banned}
        for rule in await acl_repo.list_rules(action="event.receive", target="*", role="用户"):
            if getattr(rule, "source", "") != "system" or getattr(rule, "effect", "") != "deny":
                continue
            uid = _subject_id(getattr(rule, "subject", None), "u:")
            if uid is None or uid in banned_users:
                continue
            removed += await acl_repo.delete_by_signature(
                role="用户",
                subject=rule.subject,
                action="event.receive",
                target_scope="全局",
                target="*",
            )
    except Exception:
        logger.exception("ACL orphan user-ban prune failed")

    try:
        banned_groups = {int(d.group_id) for d in groups if d.banned}
        blocked_pairs = {
            (int(d.group_id), int(u)) for d in groups for u in (getattr(d, "blocked_user_ids", None) or [])
        }
        for rule in await acl_repo.list_rules(action="event.receive", role="用户"):
            if getattr(rule, "source", "") != "system":
                continue
            target = getattr(rule, "target", "") or ""
            if not target.startswith("group:"):
                continue
            uid = _subject_id(getattr(rule, "subject", None), "u:")
            gid = _subject_id(target, "group:")
            if uid is None or gid is None or (gid, uid) in blocked_pairs:
                continue
            removed += await acl_repo.delete_by_signature(
                role="用户",
                subject=rule.subject,
                action="event.receive",
                target_scope="全局",
                target=target,
            )
        for rule in await acl_repo.list_rules(action="event.receive", target=ACL_TARGET_GROUP_BAN, role="群"):
            if getattr(rule, "source", "") != "system":
                continue
            gid = _subject_id(getattr(rule, "subject", None), "g:")
            if gid is None or gid in banned_groups:
                continue
            removed += await acl_repo.delete_by_signature(
                role="群",
                subject=rule.subject,
                action="event.receive",
                target_scope="全局",
                target=ACL_TARGET_GROUP_BAN,
            )
    except Exception:
        logger.exception("ACL orphan group-ban prune failed")

    if removed:
        clear_acl_cache()
    return removed


def _subject_id(subject: str | None, prefix: str) -> int | None:
    if not subject or not subject.startswith(prefix):
        return None
    try:
        return int(subject[len(prefix) :])
    except ValueError:
        return None


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
    try:
        out["orphans_removed"] = await prune_orphan_legacy_acl_rules()
    except Exception as exc:
        out["orphans_removed_error"] = str(exc)
    return out
