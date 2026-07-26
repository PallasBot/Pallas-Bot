"""从 PluginMetadata.extra['llm_tools'] 解析声明。"""

from __future__ import annotations

import ast
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError

if TYPE_CHECKING:
    from pathlib import Path

    from nonebot.plugin import PluginMetadata


class LlmCommandToolDecl(BaseModel):
    model_config = ConfigDict(extra="ignore")

    name: str = Field(min_length=1)
    command_id: str = Field(min_length=1)
    description: str = Field(min_length=1)
    parameters: dict[str, Any] = Field(default_factory=dict)
    command_template: str = Field(min_length=1)
    default: bool = Field(default=True, description="是否默认注入 LLM schema")
    hints: list[str] = Field(default_factory=list, description="口语触发词；硬域未命中时参与 soft_recall")
    visibility: str = Field(default="visible", description="visible | deferred")


def parse_llm_command_tool_decl(raw: dict[str, Any]) -> LlmCommandToolDecl | None:
    try:
        return LlmCommandToolDecl.model_validate(raw)
    except (ValidationError, TypeError, ValueError):
        return None


def llm_tools_from_metadata(meta: PluginMetadata | None) -> list[LlmCommandToolDecl]:
    if meta is None or not meta.extra:
        return []
    raw_list = meta.extra.get("llm_tools")
    if not isinstance(raw_list, list):
        return []
    out: list[LlmCommandToolDecl] = []
    for raw in raw_list:
        if not isinstance(raw, dict):
            continue
        decl = parse_llm_command_tool_decl(raw)
        if decl is not None and decl.default:
            out.append(decl)
    return out


def iter_loaded_plugin_llm_tools() -> list[tuple[str, str, LlmCommandToolDecl]]:
    from nonebot import get_loaded_plugins

    rows: list[tuple[str, str, LlmCommandToolDecl]] = []
    for plugin in get_loaded_plugins():
        if not plugin.name:
            continue
        meta = getattr(plugin, "metadata", None)
        title = (getattr(meta, "name", None) or plugin.name or "").strip() or plugin.name
        for decl in llm_tools_from_metadata(meta):
            rows.append((plugin.name, title, decl))  # noqa: PERF401
    return rows


def iter_package_declared_llm_tools() -> list[tuple[str, str, LlmCommandToolDecl]]:
    """扫描 packages/*/__init__.py 中的 llm_tools 声明（含未加载到本进程的插件）。"""
    from pallas.core.foundation.paths import PROJECT_ROOT

    packages_root = PROJECT_ROOT / "packages"
    if not packages_root.is_dir():
        return []
    rows: list[tuple[str, str, LlmCommandToolDecl]] = []
    seen: set[str] = set()
    for init_path in sorted(packages_root.glob("*/__init__.py")):
        plugin_name = init_path.parent.name
        for decl in parse_llm_tools_stub(init_path):
            if not decl.default or decl.name in seen:
                continue
            seen.add(decl.name)
            rows.append((plugin_name, plugin_name, decl))
    return rows


def parse_llm_tools_stub(init_path: Path) -> list[LlmCommandToolDecl]:
    """未加载插件时从 __init__.py 提取 llm_tools（dict 字面量或 llm_command_tool_row 调用）。"""
    try:
        text = init_path.read_text(encoding="utf-8")
    except OSError:
        return []
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return []
    decls: list[LlmCommandToolDecl] = []
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        if not any(isinstance(target, ast.Name) and target.id == "__plugin_meta__" for target in node.targets):
            continue
        if not isinstance(node.value, ast.Call):
            continue
        for kw in node.value.keywords:
            if kw.arg != "extra" or not isinstance(kw.value, ast.Dict):
                continue
            for key_node, value_node in zip(kw.value.keys, kw.value.values, strict=False):
                if not isinstance(key_node, ast.Constant) or key_node.value != "llm_tools":
                    continue
                if not isinstance(value_node, ast.List):
                    continue
                for item in value_node.elts:
                    raw = _ast_llm_tool_item_to_python(item)
                    if raw is None:
                        continue
                    decl = parse_llm_command_tool_decl(raw)
                    if decl is not None:
                        decls.append(decl)
    return decls


def _ast_llm_tool_item_to_python(node: ast.AST) -> dict[str, Any] | None:
    if isinstance(node, ast.Dict):
        return _ast_dict_to_python(node)
    if isinstance(node, ast.Call) and _is_llm_command_tool_row_call(node):
        return _ast_call_keywords_to_python(node)
    return None


def _is_llm_command_tool_row_call(node: ast.Call) -> bool:
    func = node.func
    if isinstance(func, ast.Name):
        return func.id == "llm_command_tool_row"
    if isinstance(func, ast.Attribute):
        return func.attr == "llm_command_tool_row"
    return False


def _ast_call_keywords_to_python(node: ast.Call) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for kw in node.keywords:
        if not kw.arg:
            continue
        value = _ast_value_to_python(kw.value)
        if value is not None or isinstance(kw.value, ast.Constant):
            out[kw.arg] = value
    return out


def _ast_dict_to_python(node: ast.Dict) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key_node, value_node in zip(node.keys, node.values, strict=False):
        if not isinstance(key_node, ast.Constant) or not isinstance(key_node.value, str):
            continue
        out[key_node.value] = _ast_value_to_python(value_node)
    return out


def _ast_value_to_python(node: ast.AST) -> Any:
    if isinstance(node, ast.Constant):
        return node.value
    if isinstance(node, ast.Dict):
        return _ast_dict_to_python(node)
    if isinstance(node, ast.List):
        return [_ast_value_to_python(item) for item in node.elts]
    return None
