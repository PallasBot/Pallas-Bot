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


def parse_llm_tools_stub(init_path: Path) -> list[LlmCommandToolDecl]:
    """未加载插件时从 __init__.py 字面量提取 llm_tools（供文档/测试）。"""
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
                    if not isinstance(item, ast.Dict):
                        continue
                    raw = _ast_dict_to_python(item)
                    decl = parse_llm_command_tool_decl(raw)
                    if decl is not None:
                        decls.append(decl)
    return decls


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
