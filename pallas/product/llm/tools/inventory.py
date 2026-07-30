"""盘点意图：口语触发 + 查询类工具判定。"""

from __future__ import annotations

from typing import TYPE_CHECKING

from pallas.product.llm.tools.contracts import ToolCapability
from pallas.product.llm.tools.discovery import TOOLS_FIND_NAME

if TYPE_CHECKING:
    from pallas.product.llm.tools.registry import LlmToolSpec

_QUERY_NAME_ACTIONS = frozenset({"list", "search", "info", "find", "catalog", "keys"})

# 偏「清单 / 都会 / 有哪些」；避免单字「会」误触
_INVENTORY_PHRASES: tuple[str, ...] = (
    "有哪些",
    "有啥",
    "都会啥",
    "都会哪些",
    "会哪些",
    "会啥",
    "你会啥",
    "你会哪些",
    "能做什么",
    "能做啥",
    "都能啥",
    "都能做什么",
    "有什么功能",
    "有哪些功能",
    "有啥功能",
    "功能列表",
    "功能清单",
    "列表",
    "清单",
    "目录",
)


def is_inventory_intent(user_text: str) -> bool:
    text = (user_text or "").strip().lower()
    if not text:
        return False
    return any(phrase in text for phrase in _INVENTORY_PHRASES)


def tool_name_action(name: str) -> str:
    raw = str(name or "").strip()
    if not raw:
        return ""
    return raw.rsplit(".", 1)[-1].strip().lower()


def is_query_tool(spec: LlmToolSpec) -> bool:
    if spec.name == TOOLS_FIND_NAME:
        return True
    caps = spec.capabilities or frozenset()
    if ToolCapability.READ_ONLY.value in caps:
        return True
    return tool_name_action(spec.name) in _QUERY_NAME_ACTIONS


def is_query_tool_name(name: str) -> bool:
    raw = str(name or "").strip()
    if raw == TOOLS_FIND_NAME:
        return True
    return tool_name_action(raw) in _QUERY_NAME_ACTIONS


def merge_inventory_overlay_specs(
    base_specs: list[LlmToolSpec] | tuple[LlmToolSpec, ...],
    *,
    user_text: str,
    domains: frozenset[str] | None,
    soft_recall_min_score: int = 6,
    soft_recall_max_candidates: int = 3,
) -> list[LlmToolSpec]:
    """盘点意图：确保 tools.find；硬域内查询类忽略 deferred；无硬域则查询类 soft-recall。"""
    from pallas.product.llm.tools.registry import iter_eligible_tool_specs
    from pallas.product.llm.tools.soft_recall import select_soft_recall_hits

    by_name: dict[str, LlmToolSpec] = {spec.name: spec for spec in base_specs}
    for spec in iter_eligible_tool_specs():
        if spec.name == TOOLS_FIND_NAME:
            by_name[spec.name] = spec
            break
    if domains:
        for spec in iter_eligible_tool_specs(domains=domains):
            if is_query_tool(spec):
                by_name[spec.name] = spec
    else:
        query_pool = tuple(
            spec for spec in iter_eligible_tool_specs() if is_query_tool(spec) and spec.name != TOOLS_FIND_NAME
        )
        if query_pool:
            hits = select_soft_recall_hits(
                user_text,
                min_score=soft_recall_min_score,
                max_candidates=soft_recall_max_candidates,
                eligible_specs=query_pool,
            )
            for hit in hits:
                by_name[hit.spec.name] = hit.spec
    return list(by_name.values())
