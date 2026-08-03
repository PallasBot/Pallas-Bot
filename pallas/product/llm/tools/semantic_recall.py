"""词面工具召回未命中时，用 embedding 在候选域内重排。"""

from __future__ import annotations

from typing import TYPE_CHECKING

from pallas.product.llm.knowledge.embedding_score import embedding_relevance_score
from pallas.product.llm.tools.soft_recall import SoftRecallHit, missing_required_params_for_text

if TYPE_CHECKING:
    from pallas.product.llm.config import LlmConfig
    from pallas.product.llm.tools.registry import LlmToolSpec

DEFAULT_SEMANTIC_RECALL_MIN_SCORE = 40


def semantic_tool_descriptor(spec: LlmToolSpec) -> str:
    from pallas.product.llm.tools.overrides import effective_tool_hints

    hints = "、".join(sorted(effective_tool_hints(spec)))
    return "\n".join(item for item in (spec.name, spec.description, hints) if item)


def select_semantic_recall_hits(
    user_text: str,
    *,
    eligible_specs: tuple[LlmToolSpec, ...],
    cfg: LlmConfig | None = None,
    min_score: int = DEFAULT_SEMANTIC_RECALL_MIN_SCORE,
    max_candidates: int = 3,
) -> list[SoftRecallHit]:
    """返回语义相近的候选；embedding 不可用时不改变既有选型。"""
    query = str(user_text or "").strip()
    if not query or not eligible_specs:
        return []
    from pallas.product.llm.config import resolve_llm_vector_retrieve
    from pallas.product.llm.knowledge.embedding_client import embedding_capability_trace, fetch_embeddings_sync

    if resolve_llm_vector_retrieve() == "keyword":
        return []
    capability = embedding_capability_trace(cfg)
    if not capability.get("semantic_available"):
        return []
    descriptors = [semantic_tool_descriptor(spec) for spec in eligible_specs]
    vectors = fetch_embeddings_sync([query, *descriptors], cfg=cfg, timeout_sec=0.8)
    if not vectors or len(vectors) != len(descriptors) + 1:
        return []
    if embedding_capability_trace(cfg).get("embedding_fallback"):
        return []
    query_vector, *descriptor_vectors = vectors
    scored = [
        SoftRecallHit(
            spec=spec,
            score=embedding_relevance_score(query_vector, vector),
            missing_required=missing_required_params_for_text(spec, query),
        )
        for spec, vector in zip(eligible_specs, descriptor_vectors, strict=True)
    ]
    ranked = sorted(scored, key=lambda item: (-item.score, item.spec.name))
    ranked = [item for item in ranked if item.score >= min_score]
    if not ranked:
        return []
    limit = max(1, int(max_candidates))
    best = ranked[0].score
    return [item for item in ranked[:limit] if item.score >= best - 3]


def semantic_recall_snapshot_fields(hits: list[SoftRecallHit]) -> dict[str, object]:
    return {
        "semantic_recall_confidence": int(hits[0].score) if hits else 0,
        "semantic_recall_candidates": [{"name": hit.spec.name, "score": hit.score} for hit in hits],
    }
