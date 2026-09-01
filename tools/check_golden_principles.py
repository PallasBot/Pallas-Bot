#!/usr/bin/env python3
"""黄金原则扫描：校验工程化地图（harness index）的文档链接与验证状态。

阶段 4「持续治理」的黄金原则检查。扫描 ``docs/developer/harness/index.md``
中表格里登记的所有文档链接，校验目标文件存在、owner 与验证状态列非空，
并报告漂移（登记了不存在的文档、或文档缺失验证状态）。

黄金原则：地图里登记的每份文档都必须真实存在，且带 owner 与验证状态，
否则智能体无法据此导航与验证。
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs"
HARNESS_INDEX = DOCS / "developer" / "harness" / "index.md"

# 匹配表格行里的文档链接：`[标题](/developer/.../xxx)` 或 `[标题](/maintainer/.../xxx)`
_LINK_RE = re.compile(r"\]\((/[^)]+)\)")
# 匹配表格行：`| ... | ... | owner | 验证状态 |`
_ROW_RE = re.compile(r"^\s*\|.*\|.*\|.*\|.*\|\s*$")


def _resolve_virtual(path: str, docs_root: Path) -> Path | None:
    """把根相对虚拟路径解析为 docs 下的文件。"""
    rel = path.lstrip("/")
    candidate = (docs_root / rel).resolve()
    if candidate.is_file():
        return candidate
    for index_name in ("README.md", "index.md"):
        indexed = (candidate / index_name).resolve()
        if indexed.is_file():
            return indexed
    with_md = candidate.with_name(candidate.name + ".md")
    if with_md.is_file():
        return with_md
    return None


def check_golden_principles(docs_root: Path, index_path: Path) -> list[str]:
    errors: list[str] = []
    if not index_path.is_file():
        return [f"harness 地图不存在：{index_path}"]
    try:
        lines = index_path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        return [f"无法读取 harness 地图：{exc}"]
    for lineno, line in enumerate(lines, start=1):
        if not _ROW_RE.match(line):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) < 4:
            continue
        owner, verify = cells[-2], cells[-1]
        if not owner or owner == "-":
            errors.append(f"index.md:{lineno} 文档缺 owner")
        if not verify or verify == "-":
            errors.append(f"index.md:{lineno} 文档缺验证状态")
        for match in _LINK_RE.finditer(line):
            target = match.group(1)
            if target.startswith(("http://", "https://")):
                continue
            resolved = _resolve_virtual(target, docs_root)
            if resolved is None:
                errors.append(f"index.md:{lineno} 登记文档不存在 `{target}`")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description="校验工程化地图的文档链接与验证状态。")
    parser.add_argument("--docs", type=Path, default=DOCS, help="docs 根目录。")
    parser.add_argument("--index", type=Path, default=HARNESS_INDEX, help="harness 地图路径。")
    args = parser.parse_args()

    errors = check_golden_principles(args.docs, args.index)
    if errors:
        print("黄金原则扫描未通过：", file=sys.stderr)
        for item in errors:
            print(f"  ✗ {item}", file=sys.stderr)
        print("修复方向：补全 owner/验证状态，或修正地图里不存在的文档链接。", file=sys.stderr)
        return 1

    print("✓ 黄金原则扫描通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
