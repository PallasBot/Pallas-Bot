#!/usr/bin/env python3
"""校验 local/plugins 与 packages 的 import 是否符合 5.x 规则。

默认（CI）packages 检查：
- 禁止 ``src.``
- 禁止 ``pallas.core.foundation.config.dotenv``（请用 ``pallas.api.config`` / ``repo_settings``）

``--strict-packages`` 为迁移目标：在上述基础上额外禁止直接 import
``pallas.core.perm``、``pallas.core.commands``、``pallas.core.limits``、
``pallas.core.storage``（含其子模块），应改用对应的 ``pallas.api.*``。
"""

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

FORBIDDEN_PREFIXES_PACKAGES = ("src.",)

FORBIDDEN_PREFIXES_PACKAGES_ALWAYS = ("pallas.core.foundation.config.dotenv",)

FORBIDDEN_PREFIXES_PACKAGES_STRICT = (
    "pallas.core.perm",
    "pallas.core.commands",
    "pallas.core.limits",
    "pallas.core.storage",
)

LOCAL_PLUGIN_ROOT = ROOT / "local" / "plugins"
PACKAGES_ROOT = ROOT / "packages"

ALLOWED_API_PREFIXES = ("pallas.api.",)


def iter_python_files(base: Path) -> list[Path]:
    if not base.is_dir():
        return []
    return sorted(p for p in base.rglob("*.py") if p.is_file())


def module_names_from_import(node: ast.AST) -> list[str]:
    names: list[str] = []
    if isinstance(node, ast.Import):
        names.extend(alias.name for alias in node.names)
    elif isinstance(node, ast.ImportFrom):
        if node.module:
            names.append(node.module)
    return names


def is_forbidden_module(mod: str, forbidden: tuple[str, ...]) -> bool:
    for prefix in forbidden:
        if mod == prefix or mod.startswith(f"{prefix}."):
            return True
    return False


def check_file(
    path: Path,
    *,
    scope: str,
    strict_packages: bool,
) -> list[str]:
    rel = path.relative_to(ROOT).as_posix()
    forbidden = FORBIDDEN_PREFIXES_LOCAL if scope == "local" else FORBIDDEN_PREFIXES_PACKAGES
    package_extra = FORBIDDEN_PREFIXES_PACKAGES_ALWAYS
    if scope == "packages" and strict_packages:
        package_extra = package_extra + FORBIDDEN_PREFIXES_PACKAGES_STRICT
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except SyntaxError as exc:
        return [f"{rel}: 语法错误 {exc}"]

    errors: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.Import, ast.ImportFrom)):
            continue
        for mod in module_names_from_import(node):
            if is_forbidden_module(mod, forbidden):
                errors.append(f"{rel}: 禁止 import `{mod}`（{scope}）")
                continue
            if scope == "packages" and is_forbidden_module(mod, package_extra):
                hint = "（请用 pallas.api.*）" if strict_packages else ""
                errors.append(f"{rel}: 禁止 import `{mod}`（packages{hint}）")
                continue
            if scope == "local" and mod.startswith("pallas.") and not mod.startswith(ALLOWED_API_PREFIXES):
                errors.append(f"{rel}: local 插件仅允许 `pallas.api.*`，发现 `{mod}`")
    return errors


def check_tree(base: Path, *, scope: str, strict_packages: bool) -> list[str]:
    errors: list[str] = []
    for path in iter_python_files(base):
        errors.extend(check_file(path, scope=scope, strict_packages=strict_packages))
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
    parser.add_argument(
        "--strict-packages",
        action="store_true",
        help="packages 额外禁止 pallas.core.perm/commands/limits/storage（迁移目标）",
    )
    args = parser.parse_args()

    errors: list[str] = []
    if args.scope in ("all", "local") and args.local.is_dir():
        errors.extend(check_tree(args.local, scope="local", strict_packages=False))
    if args.scope in ("all", "packages") and args.packages.is_dir():
        errors.extend(check_tree(args.packages, scope="packages", strict_packages=args.strict_packages))

    if errors:
        print("import 检查未通过：", file=sys.stderr)
        for item in errors:
            print(f"  ✗ {item}", file=sys.stderr)
        return 1

    print("✓ 插件 import 检查通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
