from __future__ import annotations

import time

from pallas.core.platform.ingress import route_index
from pallas.core.platform.ingress.prefix_trie import PrefixModuleTrie


def test_prefix_trie_longest_wins() -> None:
    trie = PrefixModuleTrie.from_mapping({
        "牛牛": frozenset({"chat"}),
        "牛牛帮助": frozenset({"help"}),
        "牛牛唱歌": frozenset({"sing"}),
    })
    assert trie.longest_prefix_modules("牛牛帮助 复读") == frozenset({"help"})
    assert trie.longest_prefix_modules("牛牛唱歌吧") == frozenset({"sing"})
    assert trie.longest_prefix_modules("牛牛你好") == frozenset({"chat"})
    assert trie.longest_prefix_modules("今天天气") is None


def test_prefix_trie_casefold() -> None:
    trie = PrefixModuleTrie.from_mapping({"Help": frozenset({"help"})})
    assert trie.longest_prefix_modules("help me") == frozenset({"help"})
    assert trie.has_any_prefix("HELP") is True


def test_prefix_trie_merges_modules_on_same_key() -> None:
    trie = PrefixModuleTrie()
    trie.insert("牛牛测", frozenset({"a"}))
    trie.insert("牛牛测", frozenset({"b"}))
    assert trie.longest_prefix_modules("牛牛测一下") == frozenset({"a", "b"})


def test_resolve_message_route_uses_trie_not_linear(monkeypatch) -> None:
    mapping = {f"cmd{i:04d}": frozenset({f"m{i}"}) for i in range(300)}
    mapping["牛牛帮助"] = frozenset({"help"})
    trie = PrefixModuleTrie.from_mapping(mapping)
    snapshot = route_index.RouteIndexSnapshot(
        prefix_to_modules=mapping,
        exact_to_modules={},
        regex_entries=(),
        always_run_modules=frozenset(),
        passive_modules=frozenset(),
        indexed_modules=frozenset({f"m{i}" for i in range(300)} | {"help"}),
        prefix_trie=trie,
    )
    monkeypatch.setattr(route_index, "get_route_index", lambda: snapshot)

    started = time.perf_counter()
    for _ in range(2000):
        resolution = route_index.resolve_message_route("牛牛帮助 参数")
        assert resolution.matched_modules == frozenset({"help"})
    elapsed_ms = (time.perf_counter() - started) * 1000.0
    # 线性扫 300 前缀 × 2000 次在慢机器上也远高于该阈值；Trie 应轻松低于
    assert elapsed_ms < 500.0


def test_resolve_matches_legacy_longest_prefix(monkeypatch) -> None:
    snapshot = route_index.RouteIndexSnapshot(
        prefix_to_modules={
            "牛牛": frozenset({"chat"}),
            "牛牛帮助": frozenset({"help"}),
        },
        exact_to_modules={"牛牛轮盘": frozenset({"roulette"})},
        regex_entries=(),
        always_run_modules=frozenset(),
        passive_modules=frozenset(),
        indexed_modules=frozenset({"chat", "help", "roulette"}),
        prefix_trie=None,
    )
    monkeypatch.setattr(route_index, "get_route_index", lambda: snapshot)
    assert route_index.resolve_message_route("牛牛帮助").matched_modules == frozenset({"help"})
    # exact + 最长前缀「牛牛」可同时命中（与改 Trie 前行为一致）
    assert route_index.resolve_message_route("牛牛轮盘").matched_modules == frozenset({"chat", "roulette"})
