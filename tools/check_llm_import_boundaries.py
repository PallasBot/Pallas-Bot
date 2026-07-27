#!/usr/bin/env python3
"""Fail if chat plugins import LLM ops modules directly."""

from __future__ import annotations

import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

CHAT_PLUGIN_ROOTS = (
    ROOT / "packages" / "llm_chat",
    ROOT / "packages" / "repeater",
)

FORBIDDEN_PREFIXES = (
    "pallas.product.llm.webui_config",
    "pallas.product.llm.providers_store",
    "pallas.product.llm.model_admin",
)


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


def is_forbidden_module(mod: str) -> bool:
    for prefix in FORBIDDEN_PREFIXES:
        if mod == prefix or mod.startswith(f"{prefix}."):
            return True
    return False


def check_file(path: Path) -> list[str]:
    rel = path.relative_to(ROOT).as_posix()
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except SyntaxError as exc:
        return [f"{rel}: 语法错误 {exc}"]

    errors: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.Import, ast.ImportFrom)):
            continue
        errors.extend(
            f"{rel}: 禁止 import `{mod}`（聊天插件请用 runtime_api / ops_api）"
            for mod in module_names_from_import(node)
            if is_forbidden_module(mod)
        )
    return errors


def main() -> int:
    errors: list[str] = []
    for base in CHAT_PLUGIN_ROOTS:
        for path in iter_python_files(base):
            errors.extend(check_file(path))

    if errors:
        print("LLM import 边界检查未通过：", file=sys.stderr)
        for item in errors:
            print(f"  ✗ {item}", file=sys.stderr)
        return 1

    print("✓ LLM import 边界检查通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
