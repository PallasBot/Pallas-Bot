"""在 PluginMetadata.extra 中声明知识源。"""

from __future__ import annotations

from typing import Any


def knowledge_source_row(
    *,
    source_id: str,
    title: str,
    description: str = "",
    chunks: list[dict[str, Any]] | None = None,
    retrieval_mode: str = "prompt_inject",
    scope: str = "global",
    default: bool = True,
    top_k: int = 3,
    max_chunk_len: int = 400,
) -> dict[str, Any]:
    sid = (source_id or "").strip()
    name = (title or "").strip()
    if not sid or not name:
        raise ValueError("source_id 与 title 不能为空")
    return {
        "source_id": sid,
        "title": name,
        "description": (description or name).strip(),
        "retrieval_mode": (retrieval_mode or "prompt_inject").strip(),
        "scope": (scope or "global").strip(),
        "default": bool(default),
        "top_k": int(top_k),
        "max_chunk_len": int(max_chunk_len),
        "chunks": list(chunks or []),
    }
