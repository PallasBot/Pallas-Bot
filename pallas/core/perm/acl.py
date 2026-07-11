"""Pallas-Bot ACL 引擎。

唯一对外入口：``evaluate_acl`` 与 ``acl_admin_bypass``。

设计要点：
- 默认 allow（与原 cmd_perm 的 everyone 语义一致）。
- 命中集合按 priority 取最大值；同 priority 内 deny > allow（保守）。
- admin_bypass 层独立于 priority 排序，admin_members 表里的人永远 allow
  （除非 ``pallas_admins_respect_blacklist=true`` 开关打开）。
- ``role=管理员`` 行 subject 可以是 ``"*"`` 或 ``"id:<uid>"``；
  评估期用 admin_members 表二次校验具体身份。
"""

from __future__ import annotations

import os
import time
from typing import Any, NamedTuple

ACL_ROLES = frozenset({"用户", "群", "管理员", "所有"})


class AclSubject(NamedTuple):
    """观察期主体三元组；任意字段 None 表示该维度不约束。"""

    user_id: int | None = None
    group_id: int | None = None
    bot_id: int | None = None


class AclDecision(NamedTuple):
    allow: bool
    priority: int
    source: str  # "rule" | "admin_bypass" | "fallback" | "legacy"
    rule_id: Any = None


_ACL_CACHE: dict[tuple[str, str, int | None, int | None, int | None], tuple[float, AclDecision]] = {}
_ACL_CACHE_TTL_SEC = 60.0
_ACL_CACHE_MAX = 50_000
_ADMINS_RESPECT_BLACKLIST = os.getenv("PALLAS_ADMINS_RESPECT_BLACKLIST", "").lower() in ("1", "true", "yes")


def _eval_cache_key(action: str, target: str, subject: AclSubject) -> tuple:
    return (action, target, subject.user_id, subject.group_id, subject.bot_id)


def clear_acl_cache() -> None:
    _ACL_CACHE.clear()


def _format_subject(role: str, subject: AclSubject) -> str | None:
    """把 AclSubject 转成 ACL 表里的 subject 字符串形式。"""
    if role == "用户":
        return f"u:{subject.user_id}" if subject.user_id is not None else None
    if role == "群":
        return f"g:{subject.group_id}" if subject.group_id is not None else None
    if role == "管理员":
        return "*"  # 管理员行的 subject 在 evaluate 时单独看
    if role == "所有":
        return None
    return None


def _role_matches(role: str, subject: AclSubject) -> bool:
    if role == "所有":
        return True
    if role == "用户":
        return subject.user_id is not None
    if role == "群":
        return subject.group_id is not None
    if role == "管理员":
        return subject.user_id is not None
    return False


async def _load_admin_member_user_ids(bot_id: int | None) -> set[int]:
    """读 admin_members 表，按 bot_id 过滤出 user_id 集合。"""
    try:
        from pallas.core.foundation.db import make_admin_repository

        repo = make_admin_repository()
    except Exception:
        return set()
    try:
        members = await repo.list_members()
    except Exception:
        return set()
    out: set[int] = set()
    for m in members:
        scope = getattr(m, "scope", "")
        if scope == "all":
            try:
                out.add(int(m.user_id))
            except Exception:
                continue
        elif scope == "bot":
            if bot_id is not None and getattr(m, "bot_id", None) == int(bot_id):
                try:
                    out.add(int(m.user_id))
                except Exception:
                    continue
    return out


async def acl_admin_bypass(user_id: int | None, *, bot_id: int | None = None) -> bool:
    """管理员 bypass：检测 user_id 是否在 admin_members 表中。"""
    if user_id is None:
        return False
    admin_ids = await _load_admin_member_user_ids(bot_id)
    return int(user_id) in admin_ids


async def _load_acl_rules() -> list[Any]:
    """读全部 ACL 规则；调用方负责缓存层与失败安全。"""
    try:
        from pallas.core.foundation.db import make_acl_repository

        repo = make_acl_repository()
    except Exception:
        return []
    try:
        return list(await repo.list_all())
    except Exception:
        return []


def _rule_matches(rule: Any, action: str, target: str, subject: AclSubject) -> bool:
    if rule.action != action:
        return False
    if rule.target != "*" and rule.target != target:
        return False
    scope = getattr(rule, "target_scope", "全局")
    if scope != "全局":
        prefix = "cmd" if scope == "指令" else "plugin" if scope == "插件" else None
        if prefix is None:
            return False
        if target != "*" and not target.startswith(prefix + "."):
            return False
    if not _role_matches(rule.role, subject):
        return False
    rule_subject = getattr(rule, "subject", None)
    if rule.role == "管理员":
        if rule_subject == "*":
            return subject.user_id is not None
        if rule_subject is None:
            return False
        if rule_subject.startswith("id:"):
            try:
                rid = int(rule_subject[3:])
            except ValueError:
                return False
            return subject.user_id == rid
        return False
    if rule.role == "所有":
        return True
    expected = _format_subject(rule.role, subject)
    return rule_subject == expected


async def evaluate_acl(
    *,
    action: str,
    target: str,
    subject: AclSubject,
) -> AclDecision:
    """统一 ACL 决策。三层：admin_bypass / rule / fallback。"""
    cache_key = _eval_cache_key(action, target, subject)
    now = time.monotonic()
    cached = _ACL_CACHE.get(cache_key)
    if cached is not None and cached[0] > now:
        return cached[1]

    # Layer 1: admin_bypass
    is_command_or_event = action.startswith(("cmd.", "plugin.")) or action in ("cmd.*", "event.receive")
    if is_command_or_event:
        if not _ADMINS_RESPECT_BLACKLIST and await acl_admin_bypass(subject.user_id, bot_id=subject.bot_id):
            decision = AclDecision(allow=True, priority=10_000_000, source="admin_bypass")
            _ACL_CACHE[cache_key] = (now + _ACL_CACHE_TTL_SEC, decision)
            _maybe_trim_cache(now)
            return decision

    # Layer 2: rule
    rules = await _load_acl_rules()
    matching = [r for r in rules if _rule_matches(r, action, target, subject)]
    if matching:
        max_pri = max(int(r.priority) for r in matching)
        top = [r for r in matching if int(r.priority) == max_pri]
        any_allow = any(r.effect == "allow" for r in top)
        any_deny = any(r.effect == "deny" for r in top)
        decided_allow = any_allow and not any_deny
        decision = AclDecision(
            allow=decided_allow,
            priority=max_pri,
            source="rule",
            rule_id=getattr(matching[0], "id", None),
        )
    else:
        decision = AclDecision(allow=True, priority=-1, source="fallback")

    _ACL_CACHE[cache_key] = (now + _ACL_CACHE_TTL_SEC, decision)
    _maybe_trim_cache(now)
    return decision


def _maybe_trim_cache(now: float) -> None:
    if len(_ACL_CACHE) <= _ACL_CACHE_MAX:
        return
    # 1) 淘汰过期
    stale = [k for k, (exp, _) in _ACL_CACHE.items() if exp <= now]
    for k in stale:
        _ACL_CACHE.pop(k, None)
    # 2) 还超则按插入顺序淘汰一半
    if len(_ACL_CACHE) > _ACL_CACHE_MAX:
        # dict 是插入序；删除最旧一半
        keys = list(_ACL_CACHE.keys())[: len(_ACL_CACHE) // 2]
        for k in keys:
            _ACL_CACHE.pop(k, None)
