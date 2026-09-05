"""插件元数据：静态 __plugin_meta__ 解析与归一化。"""

from __future__ import annotations

import ast
import importlib.util
from pathlib import Path
from typing import Any

from pallas.console.webui import plugin_catalog as _repo


def metadata_to_dict(meta: object | None) -> dict[str, Any] | None:
    if meta is None:
        return None
    d: dict[str, Any] = {
        "name": getattr(meta, "name", None),
        "description": (getattr(meta, "description", None) or "")[:2000],
        "usage": (getattr(meta, "usage", None) or "")[:4000],
    }
    ex = getattr(meta, "extra", None)
    if ex:
        d["extra"] = dict(ex) if isinstance(ex, dict) else ex
    typ = getattr(meta, "type", None)
    if typ is not None:
        d["type"] = str(typ)
    return d


def _parse_plugin_metadata_stub(init_path: Path) -> dict[str, Any] | None:
    def literalish(node: ast.AST) -> Any:
        if isinstance(node, ast.Constant):
            return node.value
        if isinstance(node, ast.List):
            return [literalish(item) for item in node.elts]
        if isinstance(node, ast.Tuple):
            return [literalish(item) for item in node.elts]
        if isinstance(node, ast.Set):
            return [literalish(item) for item in node.elts]
        if isinstance(node, ast.Dict):
            out: dict[str, Any] = {}
            for key_node, val_node in zip(node.keys, node.values, strict=False):
                if key_node is None:
                    continue
                key = literalish(key_node)
                if not isinstance(key, str):
                    continue
                out[key] = literalish(val_node)
            return out
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
            value = literalish(node.operand)
            if isinstance(value, (int, float)):
                return -value
        return None

    try:
        text = init_path.read_text(encoding="utf-8")
    except OSError:
        return None
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return None
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        for target in node.targets:
            if not isinstance(target, ast.Name) or target.id != "__plugin_meta__":
                continue
            if not isinstance(node.value, ast.Call):
                continue
            meta: dict[str, Any] = {}
            for kw in node.value.keywords:
                key = kw.arg
                if not key or key in ("supported_adapters", "homepage"):
                    continue
                if key in ("name", "description", "usage", "type"):
                    val = literalish(kw.value)
                    if isinstance(val, str):
                        meta[key] = val
                    continue
                if key == "extra":
                    extra = literalish(kw.value)
                    if isinstance(extra, dict) and extra:
                        menu_data = extra.get("menu_data")
                        if isinstance(menu_data, list):
                            extra = {"menu_data": menu_data}
                        else:
                            extra = {}
                        if extra:
                            meta["extra"] = extra
            if meta.get("name"):
                return meta
    return None


def _pip_plugin_metadata_stub(module_path: str) -> dict[str, Any] | None:
    """未加载时从已安装包 __init__.py 解析 __plugin_meta__。"""
    try:
        spec = importlib.util.find_spec(module_path)
    except (ImportError, ModuleNotFoundError, ValueError):
        return None
    if spec is None:
        return None
    origin = getattr(spec, "origin", None) or ""
    if not origin or origin.endswith("__init__.py"):
        init_path = Path(origin) if origin else None
    else:
        init_path = Path(origin).parent / "__init__.py"
    if init_path is None or not init_path.is_file():
        sub = getattr(spec, "submodule_search_locations", None)
        if sub:
            init_path = Path(sub[0]) / "__init__.py"
    if init_path is None or not init_path.is_file():
        return None
    return _repo._parse_plugin_metadata_stub(init_path)
