from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field


@dataclass
class _ACNode:
    children: dict[str, _ACNode] = field(default_factory=dict)
    fail: _ACNode | None = None
    output: bool = False


class AhoCorasick:
    """大小写敏感；构造后不可变。空 patterns 时 contains 恒为 False。"""

    __slots__ = ("_root",)

    def __init__(self, patterns: list[str]) -> None:
        self._root = _ACNode()
        for p in patterns:
            if not p:
                continue
            node = self._root
            for ch in p:
                node = node.children.setdefault(ch, _ACNode())
            node.output = True
        self._build_fail()

    def _build_fail(self) -> None:
        root = self._root
        root.fail = root
        q: deque[_ACNode] = deque()
        for child in root.children.values():
            child.fail = root
            q.append(child)
        while q:
            cur = q.popleft()
            for ch, child in cur.children.items():
                q.append(child)
                f = cur.fail
                assert f is not None
                while ch not in f.children and f is not root:
                    f = f.fail  # type: ignore[assignment]
                assert f is not None
                child.fail = f.children[ch] if ch in f.children else root
                child.output = child.output or child.fail.output

    def contains(self, text: str) -> bool:
        if not text:
            return False
        node = self._root
        for ch in text:
            while ch not in node.children and node is not self._root:
                assert node.fail is not None
                node = node.fail
            node = node.children[ch] if ch in node.children else self._root
            if node.output:
                return True
        return False
