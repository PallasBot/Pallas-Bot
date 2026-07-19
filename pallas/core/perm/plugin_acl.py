"""插件级 ACL：按用户禁用整个插件（治理页 / WebUI 写入 acl_rules）。"""

from __future__ import annotations

from .acl import clear_acl_cache

PLUGIN_ACL_DENY_PRIORITY = 1500
PLUGIN_ACL_TARGET_SCOPE = "插件"
PLUGIN_ACL_SOURCE = "governance"


def normalize_plugin_acl_name(plugin_name: str) -> str:
    from pallas.core.platform.bot_runtime.plugin_package_aliases import canonical_plugin_package

    clean = canonical_plugin_package((plugin_name or "").strip()) or (plugin_name or "").strip()
    return clean


def plugin_acl_key(plugin_name: str) -> str:
    return f"plugin.{normalize_plugin_acl_name(plugin_name)}"


def parse_user_id_from_acl_subject(subject: str | None) -> int | None:
    if not subject or not subject.startswith("u:"):
        return None
    try:
        uid = int(subject[2:])
    except ValueError:
        return None
    return uid if uid > 0 else None


def normalize_blocked_user_ids(user_ids: list[int]) -> list[int]:
    out: list[int] = []
    seen: set[int] = set()
    for raw in user_ids:
        try:
            uid = int(raw)
        except (TypeError, ValueError):
            continue
        if uid <= 0 or uid in seen:
            continue
        seen.add(uid)
        out.append(uid)
    out.sort()
    return out


async def list_plugin_blocked_user_ids(plugin_name: str) -> list[int]:
    key = plugin_acl_key(plugin_name)
    try:
        from pallas.core.foundation.db import make_acl_repository

        repo = make_acl_repository()
    except Exception:
        return []
    try:
        rules = await repo.list_rules(action=key, target=key, role="用户")
    except Exception:
        return []
    uids: list[int] = []
    for rule in rules:
        if getattr(rule, "effect", "") != "deny":
            continue
        if getattr(rule, "target_scope", "") != PLUGIN_ACL_TARGET_SCOPE:
            continue
        uid = parse_user_id_from_acl_subject(getattr(rule, "subject", None))
        if uid is not None:
            uids.append(uid)
    return normalize_blocked_user_ids(uids)


async def sync_plugin_blocked_user_ids(plugin_name: str, user_ids: list[int]) -> list[int]:
    """把插件禁用名单同步为 ACL deny 规则；返回规范化后的 user_id 列表。"""
    key = plugin_acl_key(plugin_name)
    desired = set(normalize_blocked_user_ids(user_ids))
    current = set(await list_plugin_blocked_user_ids(plugin_name))
    try:
        from pallas.core.foundation.db import make_acl_repository

        repo = make_acl_repository()
    except Exception:
        return sorted(desired)
    for uid in desired - current:
        await repo.upsert_rule(
            role="用户",
            subject=f"u:{uid}",
            action=key,
            target_scope=PLUGIN_ACL_TARGET_SCOPE,
            target=key,
            effect="deny",
            priority=PLUGIN_ACL_DENY_PRIORITY,
            source=PLUGIN_ACL_SOURCE,
        )
    for uid in current - desired:
        await repo.delete_by_signature(
            role="用户",
            subject=f"u:{uid}",
            action=key,
            target_scope=PLUGIN_ACL_TARGET_SCOPE,
            target=key,
        )
    clear_acl_cache()
    return sorted(desired)
