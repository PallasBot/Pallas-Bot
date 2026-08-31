#!/usr/bin/env python3
"""doc-gardening：检查 docs/ 内 Markdown 链接与锚点是否有效。

阶段 4「持续治理」的文档新鲜度检查。扫描 ``docs/`` 下所有 Markdown 的
相对链接（``](path)`` 与 ``](#anchor)``），校验目标文件存在、锚点存在，
并报告死链与失效锚点，附带修复方向。

只检查仓库内相对链接；外部 URL（http/https）与代码锚点（``code:``）跳过。
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs"

# 匹配 Markdown 链接目标：`[text](target)` 或 `[text][ref]` 的 target 部分。
_LINK_RE = re.compile(r"\]\(([^)]+)\)")
# 匹配 Markdown 标题锚点：`## 标题` 等。
_HEADING_RE = re.compile(r"^#{1,6}\s+(.+?)\s*$")
# 匹配显式锚点定义：`<a id="..."></a>` 或 `{#anchor}`。
_EXPLICIT_ANCHOR_RE = re.compile(r'<a\s+id="([^"]+)"\s*/?>|id="([^"]+)"\s*>\s*</a>|{#([^}]+)}')


def _slugify(text: str) -> str:
    """把标题转成 GitHub 风格锚点 slug。"""
    text = text.strip().lower()
    text = re.sub(r"[^\w\s-]", "", text)
    text = re.sub(r"\s+", "-", text)
    return text.strip("-")


def _collect_anchors(path: Path) -> set[str]:
    anchors: set[str] = set()
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return anchors
    for line in lines:
        match = _HEADING_RE.match(line)
        if match:
            anchors.add(_slugify(match.group(1)))
        for explicit in _EXPLICIT_ANCHOR_RE.findall(line):
            anchors.update(part for part in explicit if part)
    return anchors


def _resolve_target(link: str, *, docs_root: Path, current_dir: Path) -> tuple[Path | None, str | None]:
    """把链接 target 解析为 (文件路径, 锚点)。返回 (None, None) 表示外部/跳过。

    支持两种约定：
    - 根相对虚拟路径（``/developer/architecture/overview``）：相对 ``docs/`` 根，
      目录目标回退到 ``README.md`` / ``index.md``。
    - 相对路径（``../foo.md``）：相对当前文件所在目录。
    """
    target = link.strip()
    if not target or target.startswith(("http://", "https://", "mailto:", "#")):
        return None, None
    if "://" in target:
        return None, None
    path_part, _, anchor = target.partition("#")
    if not path_part:
        return None, None
    if path_part.startswith("/"):
        base = docs_root
        rel = path_part.lstrip("/")
    else:
        base = current_dir
        rel = path_part
    candidate = (base / rel).resolve()
    if candidate.is_file():
        return candidate, (anchor or None)
    for index_name in ("README.md", "index.md"):
        indexed = (candidate / index_name).resolve()
        if indexed.is_file():
            return indexed, (anchor or None)
    with_md = candidate.with_name(candidate.name + ".md")
    if with_md.is_file():
        return with_md, (anchor or None)
    return candidate, (anchor or None)


def check_doc_links(docs_root: Path) -> list[str]:
    """扫描 docs 下所有 Markdown，返回死链/失效锚点错误列表。"""
    errors: list[str] = []
    for path in sorted(docs_root.rglob("*.md")):
        rel = path.relative_to(docs_root).as_posix()
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except OSError:
            continue
        for lineno, line in enumerate(lines, start=1):
            for match in _LINK_RE.finditer(line):
                target = match.group(1)
                file_path, anchor = _resolve_target(target, docs_root=docs_root, current_dir=path.parent)
                if file_path is None:
                    continue
                if not file_path.is_relative_to(docs_root):
                    continue
                if not file_path.is_file():
                    errors.append(f"{rel}:{lineno} 死链 `{target}`（目标文件不存在）")
                    continue
                if anchor:
                    target_anchors = _collect_anchors(file_path)
                    if anchor not in target_anchors:
                        errors.append(f"{rel}:{lineno} 失效锚点 `{target}`（目标文件无 `{anchor}`）")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description="检查 docs/ 内 Markdown 链接与锚点有效性。")
    parser.add_argument("--docs", type=Path, default=DOCS, help="docs 根目录。")
    args = parser.parse_args()

    errors = check_doc_links(args.docs)
    if errors:
        print("doc-gardening 链接检查未通过：", file=sys.stderr)
        for item in errors:
            print(f"  ✗ {item}", file=sys.stderr)
        print("修复方向：把链接指向存在的 .md 文件，或修正锚点 slug。", file=sys.stderr)
        return 1

    print("✓ doc-gardening 链接检查通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
