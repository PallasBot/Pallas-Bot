"""通用知识源接入。"""

import importlib
from typing import TYPE_CHECKING, Any

from pallas.product.llm.knowledge.declare import knowledge_source_row
from pallas.product.llm.knowledge.models import (
    KNOWLEDGE_CONTRACT_VERSION,
    KnowledgeInjectionResult,
    KnowledgeSourceDecl,
)

if TYPE_CHECKING:
    from pallas.product.llm.knowledge.inject import enrich_system_with_knowledge_sources
    from pallas.product.llm.knowledge.registry import knowledge_metadata_payload

__all__ = [
    "KNOWLEDGE_CONTRACT_VERSION",
    "KnowledgeInjectionResult",
    "KnowledgeSourceDecl",
    "enrich_system_with_knowledge_sources",
    "knowledge_metadata_payload",
    "knowledge_source_row",
]


def __getattr__(name: str) -> Any:
    if name == "enrich_system_with_knowledge_sources":
        module = importlib.import_module("pallas.product.llm.knowledge.inject")
        value = getattr(module, name)
        globals()[name] = value
        return value
    if name == "knowledge_metadata_payload":
        module = importlib.import_module("pallas.product.llm.knowledge.registry")
        value = getattr(module, name)
        globals()[name] = value
        return value
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
