"""从 PluginMetadata.extra['knowledge_sources'] 解析声明。"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from pydantic import ValidationError

from pallas.product.llm.knowledge.models import KnowledgeSourceDecl

if TYPE_CHECKING:
    from nonebot.plugin import PluginMetadata


def parse_knowledge_source_decl(raw: dict[str, Any]) -> KnowledgeSourceDecl | None:
    try:
        return KnowledgeSourceDecl.model_validate(raw)
    except (ValidationError, TypeError, ValueError):
        return None


def knowledge_sources_from_metadata(meta: PluginMetadata | None) -> list[KnowledgeSourceDecl]:
    if meta is None or not meta.extra:
        return []
    raw_list = meta.extra.get("knowledge_sources")
    if not isinstance(raw_list, list):
        return []
    out: list[KnowledgeSourceDecl] = []
    for raw in raw_list:
        if not isinstance(raw, dict):
            continue
        decl = parse_knowledge_source_decl(raw)
        if decl is not None and decl.default:
            out.append(decl)
    return out


def iter_loaded_plugin_knowledge_sources() -> list[tuple[str, str, KnowledgeSourceDecl]]:
    from nonebot import get_loaded_plugins

    rows: list[tuple[str, str, KnowledgeSourceDecl]] = []
    for plugin in get_loaded_plugins():
        if not plugin.name:
            continue
        meta = getattr(plugin, "metadata", None)
        title = (getattr(meta, "name", None) or plugin.name or "").strip() or plugin.name
        for decl in knowledge_sources_from_metadata(meta):
            rows.append((plugin.name, title, decl))  # noqa: PERF401
    return rows
