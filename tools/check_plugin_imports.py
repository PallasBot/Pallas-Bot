#!/usr/bin/env python3
"""校验 local/plugins 与 packages 的 import 是否符合 5.x 规则。"""

from __future__ import annotations

import argparse
import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

FORBIDDEN_PREFIXES_LOCAL = (
    "pallas.core.",
    "pallas.console.",
    "pallas.product.",
    "src.",
)

FORBIDDEN_PREFIXES_PACKAGES = (
    "src.",
)

LOCAL_PLUGIN_ROOT = ROOT / "local" / "plugins"
PACKAGES_ROOT = ROOT / "packages"

ALLOWED_API_PREFIXES = (
    "pallas.api.",
)


def iter_python_files(base: Path) -> list[Path]:
    if not base.is_dir():
        return []
    return sorted(p for p in base.rglob("*.py") if p.is_file())


def module_names_from_import(node: ast.AST) -> list[str]:
    names: list[str] = []
    if isinstance(node, ast.Import):
        for alias in node.names:
            names.append(alias.name)
    elif isinstance(node, ast.ImportFrom):
        if node.module:
            names.append(node.module)
    return names


def check_file(path: Path, *, scope: str) -> list[str]:
    rel = path.relative_to(ROOT).as_posix()
    forbidden = FORBIDDEN_PREFIXES_LOCAL if scope == "local" else FORBIDDEN_PREFIXES_PACKAGES
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except SyntaxError as exc:
        return [f"{rel}: 语法错误 {exc}"]

    errors: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.Import, ast.ImportFrom)):
            continue
        for mod in module_names_from_import(node):
            if mod.startswith(forbidden):
                errors.append(f"{rel}: 禁止 import `{mod}`（{scope}）")
                continue
            if scope == "local" and mod.startswith("pallas.") and not mod.startswith(ALLOWED_API_PREFIXES):
                errors.append(f"{rel}: local 插件仅允许 `pallas.api.*`，发现 `{mod}`")
    return errors


def check_tree(base: Path, *, scope: str) -> list[str]:
    errors: list[str] = []
    for path in iter_python_files(base):
        errors.extend(check_file(path, scope=scope))
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description="检查插件目录 import 规则")
    parser.add_argument(
        "--local",
        type=Path,
        default=LOCAL_PLUGIN_ROOT,
        help="local/plugins 路径",
    )
    parser.add_argument(
        "--packages",
        type=Path,
        default=PACKAGES_ROOT,
        help="packages 内置插件路径",
    )
    parser.add_argument(
        "--scope",
        choices=("all", "local", "packages"),
        default="all",
        help="检查范围（CI 建议 packages）",
    )
    args = parser.parse_args()

    errors: list[str] = []
    if args.scope in ("all", "local") and args.local.is_dir():
        errors.extend(check_tree(args.local, scope="local"))
    if args.scope in ("all", "packages") and args.packages.is_dir():
        errors.extend(check_tree(args.packages, scope="packages"))

    if errors:
        print("import 检查未通过：", file=sys.stderr)
        for item in errors:
            print(f"  ✗ {item}", file=sys.stderr)
        return 1

    print("✓ 插件 import 检查通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
