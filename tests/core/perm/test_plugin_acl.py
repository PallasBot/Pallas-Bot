"""插件级 ACL 辅助函数单测。"""

from __future__ import annotations

from pallas.core.perm.plugin_acl import (
    normalize_blocked_user_ids,
    parse_user_id_from_acl_subject,
    plugin_acl_key,
)


def test_plugin_acl_key() -> None:
    assert plugin_acl_key("sing") == "plugin.sing"


def test_parse_user_id_from_acl_subject() -> None:
    assert parse_user_id_from_acl_subject("u:123") == 123
    assert parse_user_id_from_acl_subject("g:1") is None
    assert parse_user_id_from_acl_subject(None) is None


def test_normalize_blocked_user_ids() -> None:
    assert normalize_blocked_user_ids([100, 50, 100, 0, -1]) == [50, 100]
