"""Pallas-Bot ACL 引擎。

唯一对外入口：``evaluate_acl`` 与 ``acl_admin_bypass``。

设计要点：
- 默认 allow（与原 cmd_perm 的 everyone 语义一致）。
- 命中集合按 priority 取最大值；同 priority 内 deny > allow（保守）。
- admin_bypass 层独立于 priority 排序，admin_members 表里的人永远 allow
  （除非 ``PALLAS_ADMINS_RESPECT_BLACKLIST=true`` 开关打开）。
- ``role=管理员`` 行 subject 可以是 ``"*"`` 或 ``"id:<uid>"``；
  评估期用 admin_members 表二次校验具体身份。
- **库侧过滤**：每 (action, target) 元组的规则集合缓存至本地，缓存命中后才走
  ``_rule_matches`` 二级匹配；缓存未命中时调 repo 的 ``list_matching_rules``。
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


# 决策结果缓存（按 action+target+subject）
_DECISION_CACHE: dict[tuple[str, str, int | None, int | None, int | None], tuple[float, AclDecision]] = {}
_DECISION_CACHE_TTL_SEC = 60.0
_DECISION_CACHE_MAX = 50_000

# 规则列表缓存（按 action+target，避免 list_all）
_RULES_CACHE: dict[tuple[str, str | None], tuple[float, list[Any]]] = {}
_RULES_CACHE_TTL_SEC = 30.0
_RULES_CACHE_MAX = 1024

# admin_members 的 user_id 缓存（按 bot_id 二元组缓存）
_ADMIN_BOT_ID_CACHE: dict[tuple, tuple[float, set[int]]] = {}
_CACHE_KEY_ALL = (None, "admin_user_ids_all")

_ADMINS_RESPECT_BLACKLIST = os.getenv("PALLAS_ADMINS_RESPECT_BLACKLIST", "").lower() in ("1", "true", "yes")


def _decision_cache_key(action: str, target: str, subject: AclSubject) -> tuple:
    return (action, target, subject.user_id, subject.group_id, subject.bot_id)


def clear_acl_cache() -> None:
    _DECISION_CACHE.clear()
    _RULES_CACHE.clear()
    _ADMIN_BOT_ID_CACHE.clear()


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
    """库侧过滤 admin_members：仅查 (scope=='all' 或 scope=='bot' AND bot_id==bot_id) 的 user_id。

    30s 进程内 TTL 缓存，避免每条消息都打库。
    """
    global _ADMIN_BOT_ID_CACHE  # noqa: F824
    now = time.monotonic()
    cached = _ADMIN_BOT_ID_CACHE.get(_CACHE_KEY_ALL)
    if cached is not None and cached[0] > now and bot_id is None:
        return cached[1]
    cache_key = (bot_id, "admin_user_ids") if bot_id is not None else _CACHE_KEY_ALL
    cached = _ADMIN_BOT_ID_CACHE.get(cache_key)
    if cached is not None and cached[0] > now:
        return cached[1]
    try:
        from pallas.core.foundation.db import make_admin_repository

        repo = make_admin_repository()
    except Exception:
        return set()
    try:
        uids = await repo.list_admin_user_ids(bot_id=bot_id)
    except Exception:
        return set()
    out = set(uids)
    if len(_ADMIN_BOT_ID_CACHE) >= 64:
        _ADMIN_BOT_ID_CACHE.clear()
    _ADMIN_BOT_ID_CACHE[cache_key] = (now + 30.0, out)
    return out


async def acl_admin_bypass(user_id: int | None, *, bot_id: int | None = None) -> bool:
    """管理员 bypass：检测 user_id 是否在 admin_members 表中。"""
    if user_id is None:
        return False
    admin_ids = await _load_admin_member_user_ids(bot_id)
    return int(user_id) in admin_ids


async def _load_rules_for(action: str, target: str | None) -> list[Any]:
    """库侧过滤：按 (action, target) 调 repo.list_matching_rules。结果本地 TTL 缓存。"""
    key = (action, target if target is not None else "")
    now = time.monotonic()
    cached = _RULES_CACHE.get(key)
    if cached is not None and cached[0] > now:
        return cached[1]
    try:
        from pallas.core.foundation.db import make_acl_repository

        repo = make_acl_repository()
    except Exception:
        return []
    try:
        rules = list(await repo.list_matching_rules(action=action, target=target))
    except Exception:
        return []
    # 缓存写回
    if len(_RULES_CACHE) >= _RULES_CACHE_MAX:
        stale = [k for k, (exp, _) in _RULES_CACHE.items() if exp <= now]
        for k in stale:
            _RULES_CACHE.pop(k, None)
        if len(_RULES_CACHE) >= _RULES_CACHE_MAX:
            for k in list(_RULES_CACHE.keys())[: _RULES_CACHE_MAX // 2]:
                _RULES_CACHE.pop(k, None)
    _RULES_CACHE[key] = (now + _RULES_CACHE_TTL_SEC, rules)
    return rules


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


def _resolve_decision(matching: list[Any]) -> AclDecision:
    """rule 命中后做 priority 排序与 deny>allow 表决。"""
    max_pri = max(int(r.priority) for r in matching)
    top = [r for r in matching if int(r.priority) == max_pri]
    any_allow = any(r.effect == "allow" for r in top)
    any_deny = any(r.effect == "deny" for r in top)
    decided_allow = any_allow and not any_deny
    return AclDecision(
        allow=decided_allow,
        priority=max_pri,
        source="rule",
        rule_id=getattr(matching[0], "id", None),
    )


async def evaluate_acl(
    *,
    action: str,
    target: str,
    subject: AclSubject,
) -> AclDecision:
    """统一 ACL 决策。三层：admin_bypass / rule / fallback。

    ``target`` 传 ``None`` 时退化走 action-only 库侧过滤；通常业务方传具体值。
    """
    cache_key = _decision_cache_key(action, target, subject)
    now = time.monotonic()
    cached = _DECISION_CACHE.get(cache_key)
    if cached is not None and cached[0] > now:
        return cached[1]

    # Layer 1: admin_bypass
    is_command_or_event = action.startswith(("cmd.", "plugin.")) or action in ("cmd.*", "event.receive")
    if is_command_or_event:
        if not _ADMINS_RESPECT_BLACKLIST and await acl_admin_bypass(subject.user_id, bot_id=subject.bot_id):
            decision = AclDecision(allow=True, priority=10_000_000, source="admin_bypass")
            _cache_decision(cache_key, decision, now)
            return decision

    # Layer 2: rule
    rules = await _load_rules_for(action, target)
    matching = [r for r in rules if _rule_matches(r, action, target, subject)]
    decision = _resolve_decision(matching) if matching else AclDecision(allow=True, priority=-1, source="fallback")
    _cache_decision(cache_key, decision, now)
    return decision


def _cache_decision(cache_key: tuple, decision: AclDecision, now: float) -> None:
    """写决策缓存，满则按插入序驱逐一半。"""
    expire = now + _DECISION_CACHE_TTL_SEC
    if len(_DECISION_CACHE) >= _DECISION_CACHE_MAX:
        stale = [k for k, (exp, _) in _DECISION_CACHE.items() if exp <= now]
        for k in stale:
            _DECISION_CACHE.pop(k, None)
        if len(_DECISION_CACHE) >= _DECISION_CACHE_MAX:
            for k in list(_DECISION_CACHE.keys())[: _DECISION_CACHE_MAX // 2]:
                _DECISION_CACHE.pop(k, None)
    _DECISION_CACHE[cache_key] = (expire, decision)


def invalidate_acl_rules_cache() -> None:
    """外部 webhook（acl_api 写完后）只清规则缓存与 admin_members 缓存，决策缓存等 TTL 自然过期。"""
    _RULES_CACHE.clear()
    _ADMIN_BOT_ID_CACHE.clear()
