"""大小写不敏感的命令前缀 Trie：最长前缀命中 / 是否任一前缀命中。"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class _TrieNode:
    children: dict[str, _TrieNode] = field(default_factory=dict)
    modules: frozenset[str] | None = None


class PrefixModuleTrie:
    """装载后只读；键按 ``casefold`` 存，查询与 ``matches_command_prefix`` 对齐。"""

    __slots__ = ("_root", "_size")

    def __init__(self) -> None:
        self._root = _TrieNode()
        self._size = 0

    @classmethod
    def from_mapping(cls, prefix_to_modules: dict[str, frozenset[str]]) -> PrefixModuleTrie:
        trie = cls()
        for prefix, modules in prefix_to_modules.items():
            trie.insert(prefix, modules)
        return trie

    @classmethod
    def from_prefixes(cls, prefixes: tuple[str, ...] | list[str]) -> PrefixModuleTrie:
        trie = cls()
        empty = frozenset()
        for prefix in prefixes:
            trie.insert(prefix, empty)
        return trie

    def insert(self, prefix: str, modules: frozenset[str]) -> None:
        key = (prefix or "").strip().casefold()
        if not key:
            return
        node = self._root
        for ch in key:
            nxt = node.children.get(ch)
            if nxt is None:
                nxt = _TrieNode()
                node.children[ch] = nxt
            node = nxt
        if node.modules is None:
            self._size += 1
            node.modules = modules
        else:
            node.modules = frozenset(node.modules | modules)

    def __len__(self) -> int:
        return self._size

    def longest_prefix_modules(self, text: str) -> frozenset[str] | None:
        """返回与 text 最长前缀匹配的 module 集合；无命中则 None。"""
        node = self._root
        best: frozenset[str] | None = None
        for ch in (text or "").casefold():
            nxt = node.children.get(ch)
            if nxt is None:
                break
            node = nxt
            if node.modules is not None:
                best = node.modules
        return best

    def has_any_prefix(self, text: str) -> bool:
        """text 是否以任一已登记前缀开头（大小写不敏感）。"""
        node = self._root
        for ch in (text or "").casefold():
            nxt = node.children.get(ch)
            if nxt is None:
                return False
            node = nxt
            if node.modules is not None:
                return True
        return False
