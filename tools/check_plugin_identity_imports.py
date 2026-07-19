#!/usr/bin/env python3
"""检查主仓是否仍直接引用应迁移到 plugin_id 的插件模块路径。"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

FORBIDDEN_MODULE_RE = re.compile(
    r"\b("
    r"packages\.(?:bot_status|relogin_bot|relogin_forward|draw|maa|maa_hub|sing|chat|dream|duel|who_is_spy|pb_protocol)"
    r"|pallas_plugin_[a-z0-9_]+"
    r")\b"
)


def find_forbidden_plugin_imports(paths: list[Path]) -> list[tuple[Path, int, str]]:
    hits: list[tuple[Path, int, str]] = []
    for path in paths:
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            continue
        for lineno, line in enumerate(text.splitlines(), start=1):
            match = FORBIDDEN_MODULE_RE.search(line)
            if match:
                hits.append((path, lineno, match.group(1)))
    return hits


def iter_python_files(base: Path) -> list[Path]:
    if base.is_file():
        return [base] if base.suffix == ".py" else []
    if not base.is_dir():
        return []
    return sorted(p for p in base.rglob("*.py") if p.is_file())


def main() -> int:
    parser = argparse.ArgumentParser(description="检查 plugin identity 迁移中的禁用模块路径")
    parser.add_argument("paths", nargs="*", type=Path, help="待检查文件或目录；默认检查 pallas、packages、tests、tools")
    args = parser.parse_args()

    targets = args.paths or [ROOT / "pallas", ROOT / "packages", ROOT / "tests", ROOT / "tools"]
    files: list[Path] = []
    seen: set[Path] = set()
    for target in targets:
        for path in iter_python_files(target):
            if path not in seen:
                seen.add(path)
                files.append(path)

    hits = find_forbidden_plugin_imports(files)
    if hits:
        print("plugin identity import 检查未通过：", file=sys.stderr)
        for path, lineno, module_name in hits:
            rel = path.relative_to(ROOT).as_posix() if path.is_absolute() else path.as_posix()
            print(f"  ✗ {rel}:{lineno} 禁止直接引用 `{module_name}`", file=sys.stderr)
        return 1

    print("✓ plugin identity import 检查通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
