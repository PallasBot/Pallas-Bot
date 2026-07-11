"""ACL 引擎纯逻辑单测：rule 层 priority 与 subject 解析。"""

from __future__ import annotations

from dataclasses import dataclass

from pallas.core.perm.acl import AclSubject, _rule_matches


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
    r = _FakeRule("群", "g:42", "event.receive", "全局", "*", "deny", 2000)
    assert _rule_matches(r, "event.receive", "*", AclSubject(group_id=42)) is True
    assert _rule_matches(r, "event.receive", "*", AclSubject(group_id=99)) is False


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


def test_role_all_matches() -> None:
    r = _FakeRule("所有", None, "event.receive", "全局", "*", "deny", 100)
    assert _rule_matches(r, "event.receive", "*", AclSubject(user_id=1, group_id=2)) is True
    assert _rule_matches(r, "event.receive", "*", AclSubject()) is True
