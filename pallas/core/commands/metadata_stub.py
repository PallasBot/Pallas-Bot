"""从插件 __init__.py 静态解析 command_permissions / command_limits 声明。"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Any


def static_str(value: ast.AST, names: dict[str, str] | None = None) -> str | None:
    if isinstance(value, ast.Constant) and isinstance(value.value, str):
        return value.value
    if isinstance(value, ast.Name):
        return (names or {}).get(value.id)
    if isinstance(value, ast.JoinedStr):
        parts: list[str] = []
        for part in value.values:
            if isinstance(part, ast.Constant) and isinstance(part.value, str):
                parts.append(part.value)
            elif (
                isinstance(part, ast.FormattedValue)
                and part.conversion == -1
                and part.format_spec is None
                and isinstance(part.value, ast.Name)
                and names is not None
                and part.value.id in names
            ):
                parts.append(names[part.value.id])
            else:
                return None
        return "".join(parts)
    return None


def const_str(value: ast.AST, names: dict[str, str] | None = None) -> str | None:
    result = static_str(value, names)
    return result.strip() if result is not None else None


def top_level_string_names(tree: ast.Module, before_line: int) -> dict[str, str]:
    names: dict[str, str] = {}
    for node in tree.body:
        if node.lineno >= before_line:
            break
        if isinstance(node, ast.Assign):
            targets = node.targets
            value = node.value
        elif isinstance(node, ast.AnnAssign):
            targets = [node.target]
            value = node.value
        elif isinstance(node, ast.AugAssign):
            targets = [node.target]
            value = None
        else:
            targets = []
            value = None
        resolved = static_str(value, names) if value is not None else None
        for target in targets:
            for bound_name in (part for part in ast.walk(target) if isinstance(part, ast.Name)):
                if isinstance(bound_name.ctx, ast.Store):
                    if resolved is None or not isinstance(target, ast.Name):
                        names.pop(bound_name.id, None)
                    else:
                        names[bound_name.id] = resolved
        if value is not None:
            for part in ast.walk(value):
                if isinstance(part, ast.Name) and isinstance(part.ctx, (ast.Store, ast.Del)):
                    names.pop(part.id, None)
        if not targets:
            bound_names = {
                part.id
                for part in ast.walk(node)
                if isinstance(part, ast.Name) and isinstance(part.ctx, (ast.Store, ast.Del))
            }
            for part in ast.walk(node):
                if isinstance(part, ast.alias):
                    bound_names.add(part.asname or part.name.split(".", 1)[0])
            bound_names.update(
                part.name
                for part in ast.walk(node)
                if isinstance(part, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
            )
            for bound_name in bound_names:
                names.pop(bound_name, None)
    return names


def const_int(value: ast.AST) -> int | None:
    if isinstance(value, ast.Constant) and isinstance(value.value, int):
        return int(value.value)
    return None


def extract_call_name(node: ast.AST) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return ""


def extract_literal_dict(node: ast.AST, names: dict[str, str] | None = None) -> dict[str, Any] | None:
    if not isinstance(node, ast.Dict):
        return None
    out: dict[str, Any] = {}
    for key_node, value_node in zip(node.keys, node.values, strict=False):
        key = const_str(key_node, names) if key_node is not None else None
        if not key:
            continue
        str_value = const_str(value_node, names)
        if str_value is not None:
            out[key] = str_value
            continue
        int_value = const_int(value_node)
        if int_value is not None:
            out[key] = int_value
    return out


def extract_decl_row(node: ast.AST, names: dict[str, str] | None = None) -> dict[str, Any] | None:
    if not isinstance(node, ast.Call):
        return extract_literal_dict(node, names)
    call_name = extract_call_name(node.func)
    if call_name == "command_perm_row":
        if len(node.args) >= 3:
            return {
                "id": const_str(node.args[0], names) or "",
                "label": const_str(node.args[1], names) or "",
                "default": const_str(node.args[2], names) or "",
            }
    if call_name == "command_limit_row":
        if len(node.args) >= 2:
            cd = const_int(node.args[1])
            return {
                "id": const_str(node.args[0], names) or "",
                "cd_sec": cd if cd is not None else -1,
            }
    return extract_literal_dict(node, names)


def extract_decl_rows(node: ast.AST, names: dict[str, str] | None = None) -> list[dict[str, Any]]:
    if isinstance(node, (ast.List, ast.Tuple)):
        return [row for item in node.elts if (row := extract_decl_row(item, names)) is not None]
    if isinstance(node, ast.Call):
        rows: list[dict[str, Any]] = []
        for arg in node.args:
            row = extract_decl_row(arg, names)
            if row is not None:
                rows.append(row)
        return rows
    return []


def _extra_rows_from_plugin_metadata_call(
    node: ast.Call,
    names: dict[str, str] | None = None,
) -> tuple[str, dict[str, list[dict[str, Any]]]]:
    plugin_name = ""
    extra_rows: dict[str, list[dict[str, Any]]] = {}
    for keyword in node.keywords:
        if keyword.arg == "name":
            plugin_name = const_str(keyword.value) or ""
            continue
        if keyword.arg != "extra" or not isinstance(keyword.value, ast.Dict):
            continue
        for extra_key_node, extra_value_node in zip(keyword.value.keys, keyword.value.values, strict=False):
            extra_key = const_str(extra_key_node) if extra_key_node is not None else None
            if extra_key in {"command_permissions", "command_limits"}:
                extra_rows[extra_key] = extract_decl_rows(extra_value_node, names)
    return plugin_name, extra_rows


def parse_plugin_metadata_extra_stub(init_path: Path) -> dict[str, Any] | None:
    """解析 __plugin_meta__ / PluginMetadata 中的 name 与 extra 声明行。"""
    try:
        text = init_path.read_text(encoding="utf-8")
    except OSError:
        return None
    try:
        tree = ast.parse(text, filename=str(init_path))
    except SyntaxError:
        return None

    plugin_name = ""
    extra_rows: dict[str, list[dict[str, Any]]] = {}
    for node in tree.body:
        if isinstance(node, ast.Assign):
            if not any(isinstance(target, ast.Name) and target.id == "__plugin_meta__" for target in node.targets):
                continue
            if not isinstance(node.value, ast.Call):
                continue
            plugin_name, extra_rows = _extra_rows_from_plugin_metadata_call(
                node.value,
                top_level_string_names(tree, node.lineno),
            )
            break
    if not plugin_name and not extra_rows:
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            if extract_call_name(node.func) != "PluginMetadata":
                continue
            plugin_name, extra_rows = _extra_rows_from_plugin_metadata_call(
                node,
                top_level_string_names(tree, node.lineno),
            )
            break
    if not plugin_name and not extra_rows:
        return None
    return {"name": plugin_name, **extra_rows}


def iter_plugin_init_paths_for_disk_scan() -> list[tuple[str, Path]]:
    """未加载插件时从磁盘/已安装包定位 __init__.py：(canonical_package, path)。"""
    import importlib.util

    from pallas.console.webui.plugin_catalog import (
        discover_extra_plugin_packages,
        discover_plugin_packages,
        discover_pyproject_plugin_modules,
    )
    from pallas.core.foundation.paths import PROJECT_ROOT
    from pallas.core.platform.bot_runtime.plugin_package_aliases import canonical_plugin_package

    out: list[tuple[str, Path]] = []
    seen: set[str] = set()

    def add(package: str, init_path: Path) -> None:
        canon = canonical_plugin_package((package or "").strip()) or (package or "").strip()
        if not canon or canon in seen or not init_path.is_file():
            return
        out.append((canon, init_path))
        seen.add(canon)

    for package in discover_plugin_packages():
        add(package, PROJECT_ROOT / "packages" / package / "__init__.py")

    from pallas.core.platform.bot_runtime.plugin_matrix import EXTRA_PACKAGE_MODULES

    for module_paths in EXTRA_PACKAGE_MODULES.values():
        for module_path in module_paths:
            try:
                spec = importlib.util.find_spec(module_path)
            except (ImportError, ModuleNotFoundError, ValueError):
                continue
            if spec is None:
                continue
            origin = getattr(spec, "origin", None) or ""
            init_path: Path | None
            if not origin or origin.endswith("__init__.py"):
                init_path = Path(origin) if origin else None
            else:
                init_path = Path(origin).parent / "__init__.py"
            if init_path is None or not init_path.is_file():
                sub = getattr(spec, "submodule_search_locations", None)
                if sub:
                    init_path = Path(sub[0]) / "__init__.py"
            if init_path is None or not init_path.is_file():
                continue
            short = module_path.rsplit(".", 1)[-1]
            add(short, init_path)
            add(module_path, init_path)

    for package, root in discover_extra_plugin_packages().items():
        add(package, root / "__init__.py")

    for module_path in discover_pyproject_plugin_modules():
        try:
            spec = importlib.util.find_spec(module_path)
        except (ImportError, ModuleNotFoundError, ValueError):
            continue
        if spec is None:
            continue
        origin = getattr(spec, "origin", None) or ""
        init_path: Path | None
        if not origin or origin.endswith("__init__.py"):
            init_path = Path(origin) if origin else None
        else:
            init_path = Path(origin).parent / "__init__.py"
        if init_path is None or not init_path.is_file():
            sub = getattr(spec, "submodule_search_locations", None)
            if sub:
                init_path = Path(sub[0]) / "__init__.py"
        if init_path is None or not init_path.is_file():
            continue
        short = module_path.rsplit(".", 1)[-1]
        add(short, init_path)
        add(module_path, init_path)

    return out
