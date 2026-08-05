from __future__ import annotations

from pallas.core.platform.ingress.policy_registry import (
    FanoutScope,
    fanout_policies_for_plugin,
    parse_fanout_policies,
    parse_fanout_policy,
    policy_matches_text,
    text_matches_plugin_fanout,
)


def test_empty_plugin_name_has_no_fanout_policies() -> None:
    assert fanout_policies_for_plugin("") == ()


def test_parse_fanout_policy_shard_only() -> None:
    entry = parse_fanout_policy({
        "scope": "shard_only",
        "plaintexts": ["牛牛报数"],
        "normalize_trailing_punct": True,
    })
    assert entry is not None
    assert entry.scope == FanoutScope.SHARD_ONLY
    assert policy_matches_text(entry, "牛牛报数！")


def test_parse_fanout_policy_regex() -> None:
    entry = parse_fanout_policy({"regexes": [r"^牛牛轮盘$"]})
    assert entry is not None
    assert policy_matches_text(entry, "牛牛轮盘")
    assert not policy_matches_text(entry, "牛牛轮盘踢人")


def test_parse_fanout_policies_supports_distinct_scopes() -> None:
    entries = parse_fanout_policies([
        {"scope": "always", "plaintexts": ["我的牛牛"]},
        {"scope": "shard_only", "plaintexts": ["牛牛报数"]},
    ])

    assert [(entry.scope, entry.plaintexts) for entry in entries] == [
        (FanoutScope.ALWAYS, frozenset({"我的牛牛"})),
        (FanoutScope.SHARD_ONLY, frozenset({"牛牛报数"})),
    ]


def test_text_matches_plugin_fanout(monkeypatch) -> None:
    from types import SimpleNamespace

    from pallas.core.platform.ingress.policy_registry import clear_ingress_policy_cache

    plugins = [
        SimpleNamespace(
            name="drink",
            metadata=SimpleNamespace(extra={"ingress_fanout": {"scope": "always", "plaintexts": ["牛牛喝酒"]}}),
        )
    ]
    monkeypatch.setattr("pallas.core.platform.ingress.policy_registry.get_loaded_plugins", lambda: plugins)
    clear_ingress_policy_cache()
    assert text_matches_plugin_fanout("牛牛喝酒", "drink")
    assert not text_matches_plugin_fanout("牛牛干杯", "drink")


def test_text_matches_plugin_additional_fanout(monkeypatch) -> None:
    from types import SimpleNamespace

    from pallas.core.platform.ingress.policy_registry import clear_ingress_policy_cache

    plugins = [
        SimpleNamespace(
            name="bot_status",
            metadata=SimpleNamespace(
                extra={
                    "ingress_fanout": {"scope": "shard_only", "plaintexts": ["牛牛报数"]},
                    "ingress_fanout_additional": [{"scope": "always", "plaintexts": ["我的牛牛"]}],
                }
            ),
        )
    ]
    monkeypatch.setattr("pallas.core.platform.ingress.policy_registry.get_loaded_plugins", lambda: plugins)
    clear_ingress_policy_cache()

    assert text_matches_plugin_fanout("牛牛报数", "bot_status")
    assert text_matches_plugin_fanout("我的牛牛", "bot_status")
