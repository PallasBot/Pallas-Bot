"""ACL 引擎纯逻辑单测：rule 层 priority、subject 与 target 约定。"""

from __future__ import annotations

from dataclasses import dataclass

from pallas.core.perm.acl import (
    ACL_TARGET_ANY,
    ACL_TARGET_GROUP_BAN,
    AclDecision,
    AclSubject,
    _resolve_decision,
    _rule_matches,
    group_block_target,
)


@dataclass
class _FakeRule:
    role: str
    subject: str | None
    action: str
    target_scope: str
    target: str
    effect: str
    priority: int


def test_role_match_priority() -> None:
    r = _FakeRule("用户", "u:123", "event.receive", "全局", "*", "deny", 2000)
    assert _rule_matches(r, "event.receive", "*", AclSubject(user_id=123)) is True


def test_role_match_group() -> None:
    r = _FakeRule("群", "g:42", "event.receive", "全局", ACL_TARGET_GROUP_BAN, "deny", 2000)
    assert _rule_matches(r, "event.receive", ACL_TARGET_GROUP_BAN, AclSubject(group_id=42)) is True
    assert _rule_matches(r, "event.receive", ACL_TARGET_GROUP_BAN, AclSubject(group_id=99)) is False


def test_group_ban_target_does_not_match_user_group_block_target() -> None:
    """群自身封禁 target=group，不应被误当成 group:{gid} 用户黑名单。"""
    r = _FakeRule("群", "g:42", "event.receive", "全局", ACL_TARGET_GROUP_BAN, "deny", 2000)
    assert _rule_matches(r, "event.receive", group_block_target(42), AclSubject(group_id=42)) is False


def test_group_block_user_target() -> None:
    r = _FakeRule("用户", "u:7", "event.receive", "全局", group_block_target(42), "deny", 1000)
    assert _rule_matches(r, "event.receive", group_block_target(42), AclSubject(user_id=7, group_id=42)) is True
    assert _rule_matches(r, "event.receive", ACL_TARGET_ANY, AclSubject(user_id=7, group_id=42)) is False


def test_admin_subject_star() -> None:
    r = _FakeRule("管理员", "*", "event.receive", "全局", "*", "deny", 100)
    assert _rule_matches(r, "event.receive", "*", AclSubject(user_id=123)) is True
    assert _rule_matches(r, "event.receive", "*", AclSubject()) is False


def test_admin_subject_specific_uid() -> None:
    r = _FakeRule("管理员", "id:123", "event.receive", "全局", "*", "deny", 100)
    assert _rule_matches(r, "event.receive", "*", AclSubject(user_id=123)) is True
    assert _rule_matches(r, "event.receive", "*", AclSubject(user_id=456)) is False


def test_target_scope_filter() -> None:
    rule = _FakeRule("用户", "u:1", "cmd.foo", "指令", "cmd.foo", "deny", 100)
    assert _rule_matches(rule, "cmd.foo", "cmd.foo", AclSubject(user_id=1)) is True
    assert _rule_matches(rule, "cmd.foo", "cmd.bar", AclSubject(user_id=1)) is False


def test_target_scope_accepts_bare_command_id_with_cmd_action() -> None:
    """evaluate 传 cmd. 前缀、规则写裸 id 时仍应命中（#229 Sourcery）。"""
    rule = _FakeRule("用户", "u:1", "cmd.foo", "指令", "foo", "deny", 100)
    assert _rule_matches(rule, "cmd.foo", "cmd.foo", AclSubject(user_id=1)) is True


def test_role_all_matches() -> None:
    r = _FakeRule("所有", None, "event.receive", "全局", "*", "deny", 100)
    assert _rule_matches(r, "event.receive", "*", AclSubject(user_id=1, group_id=2)) is True
    assert _rule_matches(r, "event.receive", "*", AclSubject()) is True


def test_resolve_decision_deny_beats_allow_same_priority() -> None:
    matching = [
        _FakeRule("用户", "u:1", "event.receive", "全局", "*", "allow", 100),
        _FakeRule("用户", "u:1", "event.receive", "全局", "*", "deny", 100),
    ]
    decision = _resolve_decision(matching)
    assert decision == AclDecision(allow=False, priority=100, source="rule", rule_id=None)


def test_group_block_target_helper() -> None:
    assert group_block_target(123) == "group:123"
