"""软召回：selective 未命中硬域时，按 hints/描述打分注入少量工具。"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from pallas.product.llm.tools.score import score_tool_text

if TYPE_CHECKING:
    from pallas.product.llm.tools.registry import LlmToolSpec

DEFAULT_SOFT_RECALL_MIN_SCORE = 6
DEFAULT_SOFT_RECALL_MAX_CANDIDATES = 3

_PUNCT_RE = re.compile(r"[\s,，。！？!?、；;：:…~～「」『』【】\[\]()（）\"']+")


@dataclass(frozen=True, slots=True)
class SoftRecallHit:
    spec: LlmToolSpec
    score: int
    missing_required: tuple[str, ...]


def required_param_names(spec: LlmToolSpec) -> tuple[str, ...]:
    params = spec.parameters if isinstance(spec.parameters, dict) else {}
    raw = params.get("required")
    if not isinstance(raw, list):
        return ()
    return tuple(str(item).strip() for item in raw if str(item).strip())


def residual_after_cues(user_text: str, cues: frozenset[str] | set[str]) -> str:
    text = str(user_text or "").strip()
    if not text:
        return ""
    residual = text
    for cue in sorted((str(c).strip() for c in cues if str(c).strip()), key=len, reverse=True):
        if cue and cue in residual:
            residual = residual.replace(cue, " ")
    residual = _PUNCT_RE.sub(" ", residual)
    return " ".join(residual.split()).strip()


def missing_required_params_for_text(spec: LlmToolSpec, user_text: str) -> tuple[str, ...]:
    """启发式：去掉 hints 后几乎无残留，则视为缺少 required。"""
    required = required_param_names(spec)
    if not required:
        return ()
    from pallas.product.llm.tools.overrides import effective_tool_hints

    residual = residual_after_cues(user_text, effective_tool_hints(spec))
    if len(residual) < 2:
        return required
    return ()


def select_soft_recall_hits(
    user_text: str,
    *,
    min_score: int = DEFAULT_SOFT_RECALL_MIN_SCORE,
    max_candidates: int = DEFAULT_SOFT_RECALL_MAX_CANDIDATES,
    eligible_specs: tuple[LlmToolSpec, ...] | None = None,
) -> list[SoftRecallHit]:
    text = (user_text or "").strip()
    if not text:
        return []
    from pallas.product.llm.tools.overrides import effective_tool_hints
    from pallas.product.llm.tools.registry import iter_eligible_tool_specs

    specs = eligible_specs if eligible_specs is not None else iter_eligible_tool_specs()
    scored: list[SoftRecallHit] = []
    for spec in specs:
        hints = effective_tool_hints(spec)
        if not hints and not (spec.description or "").strip():
            continue
        score = score_tool_text(
            text,
            name=spec.name,
            description=spec.description,
            hints=hints,
        )
        if score < int(min_score):
            continue
        scored.append(
            SoftRecallHit(
                spec=spec,
                score=score,
                missing_required=missing_required_params_for_text(spec, text),
            )
        )
    scored.sort(key=lambda item: (-item.score, item.spec.name))
    limit = max(1, int(max_candidates))
    top = scored[:limit]
    if not top:
        return []
    best = top[0].score
    return [item for item in top if item.score >= best - 2]


def soft_recall_snapshot_fields(hits: list[SoftRecallHit]) -> dict[str, Any]:
    if not hits:
        return {
            "selection_source": "soft_recall",
            "soft_recall_confidence": 0,
            "soft_recall_candidates": [],
            "ask_before_call": False,
            "missing_required_params": {},
        }
    missing_map = {hit.spec.name: list(hit.missing_required) for hit in hits if hit.missing_required}
    return {
        "selection_source": "soft_recall",
        "soft_recall_confidence": int(hits[0].score),
        "soft_recall_candidates": [
            {"name": hit.spec.name, "score": hit.score, "missing_required": list(hit.missing_required)} for hit in hits
        ],
        "ask_before_call": any(bool(hit.missing_required) for hit in hits),
        "missing_required_params": missing_map,
    }
