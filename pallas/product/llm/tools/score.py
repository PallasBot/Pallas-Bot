"""工具口语打分：hints / 名称 / 描述子串匹配。"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pallas.product.llm.tools.registry import LlmToolSpec

# 达到该分才把工具域并入 selective 推断（避免单字误触）
DEFAULT_MIN_SCORE = 6

# 口语与 hint 共用的祈使词干（跨插件通用，不写死模板名）
_IMPERATIVE_STEMS: tuple[str, ...] = (
    "做个",
    "来个",
    "放首",
    "来首",
    "画个",
    "画张",
    "来张",
    "来杯",
    "整首",
)


def _imperative_stem_bonus(query: str, hints: frozenset[str] | set[str] | list[str]) -> int:
    """query 与任一 hint 共享祈使词干时加分；优先点名语境，降低「做个饭」误触。"""
    q = (query or "").strip().lower()
    if not q:
        return 0
    hint_blob = " ".join(str(h).strip().lower() for h in hints if str(h).strip())
    if not hint_blob:
        return 0
    addressed = "牛牛" in q
    for stem in _IMPERATIVE_STEMS:
        if stem in q and stem in hint_blob:
            if addressed:
                return 6
            if any(tag in q for tag in ("表情", "meme", "歌", "曲", "图", "酒", "杯")):
                return 6
            return 0
    return 0


def score_tool_text(
    query: str,
    *,
    name: str,
    description: str,
    hints: frozenset[str] | set[str],
) -> int:
    q = (query or "").strip().lower()
    if not q:
        return 0
    score = 0
    hay_name = name.lower()
    hay_desc = (description or "").lower()
    if q in hay_name:
        score += 8
    if q in hay_desc:
        score += 4
    for hint in hints:
        h = str(hint or "").strip().lower()
        if not h:
            continue
        if q == h or h in q:
            score += 6
        elif q in h and len(q) >= 2:
            score += 4
        elif any(part and len(part) >= 2 and part in h for part in q.split()):
            score += 2
    score += _imperative_stem_bonus(q, hints)
    return score


def domains_from_tool_scores(
    user_text: str,
    *,
    min_score: int = DEFAULT_MIN_SCORE,
) -> frozenset[str]:
    """对已注册工具打分，高分工具的域并入 selective。"""
    text = (user_text or "").strip().lower()
    if not text:
        return frozenset()
    from pallas.product.llm.tools.overrides import effective_tool_hints
    from pallas.product.llm.tools.registry import list_registered_tools
    from pallas.product.llm.tools.select import selective_domains

    domains: set[str] = set()
    for spec in list_registered_tools():
        hints = effective_tool_hints(spec)
        if not hints and not spec.description:
            continue
        score = score_tool_text(
            text,
            name=spec.name,
            description=spec.description,
            hints=hints,
        )
        if score < min_score:
            continue
        domains.update(selective_domains(frozenset(str(d).strip() for d in spec.domains if str(d).strip())))
    return frozenset(domains)


def score_registered_tools(user_text: str) -> list[tuple[int, LlmToolSpec]]:
    from pallas.product.llm.tools.overrides import effective_tool_hints
    from pallas.product.llm.tools.registry import list_registered_tools

    text = (user_text or "").strip().lower()
    scored: list[tuple[int, LlmToolSpec]] = []
    if not text:
        return scored
    for spec in list_registered_tools():
        hints = effective_tool_hints(spec)
        score = score_tool_text(
            text,
            name=spec.name,
            description=spec.description,
            hints=hints,
        )
        if score > 0:
            scored.append((score, spec))
    scored.sort(key=lambda item: (-item[0], item[1].name))
    return scored
