"""选型预览：给定话术返回命中域与候选工具。"""

from __future__ import annotations

from typing import Any

from pallas.product.llm.tools.patterns import domains_from_structure
from pallas.product.llm.tools.score import score_registered_tools
from pallas.product.llm.tools.select import (
    domains_from_registered_tool_hints,
    infer_tool_domains,
)


def preview_tool_intent(user_text: str, *, task: str = "llm_chat") -> dict[str, Any]:
    text = (user_text or "").strip()
    from pallas.product.llm.tools.registry import tool_catalog_for_chat

    domains = infer_tool_domains(text)
    structure = domains_from_structure(text)
    hint_domains = domains_from_registered_tool_hints(text)
    scored = score_registered_tools(text)[:16]
    catalog = tool_catalog_for_chat(task=task, user_text=text)
    schema_tools = [item.name for item in catalog.tools] if catalog is not None else []
    return {
        "text": text,
        "domains": sorted(domains),
        "structure_domains": sorted(structure),
        "hint_domains": sorted(hint_domains),
        "top_scores": [
            {
                "name": spec.name,
                "score": score,
                "domains": sorted(spec.domains),
                "visibility": str(spec.visibility or "visible"),
            }
            for score, spec in scored
        ],
        "schema_tools": schema_tools,
        "schema_count": int(catalog.selection.schema_count) if catalog is not None else 0,
        "selective_empty": catalog is None and bool(text),
    }
