from __future__ import annotations

from pallas.core.platform.ingress.policy_registry import (
    FanoutScope,
    parse_fanout_policy,
    policy_matches_text,
    text_matches_plugin_fanout,
)


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
