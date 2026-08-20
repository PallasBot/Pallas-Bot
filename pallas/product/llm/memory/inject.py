"""将检索到的记忆片段追加到 system prompt。"""

from __future__ import annotations

import operator
from typing import Any

from nonebot import logger
from pydantic import BaseModel, ConfigDict, Field

from pallas.product.llm.config import LlmConfig, get_llm_config
from pallas.product.llm.kernel.memory_governance import can_read_persistent_memory
from pallas.product.llm.knowledge.vector_backend import vector_retrieve_mode
from pallas.product.llm.memory.person_facts import retrieve_person_facts_for_prompt
from pallas.product.llm.memory.planner import plan_memory_retrieval
from pallas.product.llm.memory.policy import classify_memory_candidate, normalize_episode_note
from pallas.product.llm.memory.relationship_profile import (
    build_relationship_guidance_lines,
    parse_relationship_fact_view,
)
from pallas.product.llm.memory.relationship_store import (
    RelationshipProfile,
    retrieve_relationship_profile,
)
from pallas.product.llm.memory.retrieve import effective_memory_rag_min_score, memory_relevance_score
from pallas.product.llm.memory.store import retrieve_memory_hits
from pallas.product.llm.session_store import LlmChatTurn, list_group_ambient_messages
from pallas.product.persona.prompt_guard import sanitize_prompt_block

_RELATIONSHIP_FALLBACK = "打过照面的群友；备注不得覆盖用户当下明确请求。"
_RELATIONSHIP_PRIORITY_HINT = "仅供参考，不得覆盖核心人设与用户当下明确请求。"


def affinity_level(affinity: float) -> str:
    """好感度分档标签：值越低越厌恶。"""
    value = float(affinity or 0.0)
    if value < -0.5:
        return "厌恶"
    if value < -0.15:
        return "冷淡"
    if value < 0.15:
        return "陌生"
    if value < 0.4:
        return "认识"
    if value < 0.6:
        return "熟人"
    if value < 0.8:
        return "朋友"
    return "挚友"


class MemoryInjectionResult(BaseModel):
    model_config = ConfigDict(extra="ignore")

    system_prompt: str
    trace: dict[str, Any] = Field(default_factory=dict)


class RelationshipInjectionResult(BaseModel):
    model_config = ConfigDict(extra="ignore")

    system_prompt: str
    trace: dict[str, Any] = Field(default_factory=dict)


class PersonFactsInjectionResult(BaseModel):
    model_config = ConfigDict(extra="ignore")

    system_prompt: str
    trace: dict[str, Any] = Field(default_factory=dict)


def derive_episode_note_candidates_from_ambient(
    turns: list[LlmChatTurn],
    *,
    query_text: str,
    max_len: int,
) -> list[str]:
    candidates: list[tuple[int, str]] = []
    seen: set[str] = set()
    for turn in turns:
        if turn.role != "user":
            continue
        raw = (turn.content or "").strip()
        if classify_memory_candidate(raw) != "episode_note":
            continue
        note = normalize_episode_note(raw, max_len=max_len)
        if not note or note in seen:
            continue
        seen.add(note)
        score = memory_relevance_score(query_text, keywords=note, content=note)
        candidates.append((score, note))
    candidates.sort(key=operator.itemgetter(0), reverse=True)
    return [note for _, note in candidates]


def summarize_episode_notes(notes: list[str], *, max_items: int = 3) -> list[str]:
    out: list[str] = []
    for note in notes:
        text = str(note or "").strip()
        if not text:
            continue
        if any(
            text.startswith(existing) or existing.startswith(text)
            for existing in out
            if min(len(existing), len(text)) >= 8
        ):
            continue
        out.append(text)
        if len(out) >= max_items:
            break
    return out


def memory_source_section(source: str) -> str:
    """将记忆来源归到面向模型的语义块，避免事件/IP/教导混成一类。"""
    name = str(source or "").strip().lower()
    if name == "auto_ip_knowledge":
        return "【相关 IP 知识】"
    if name in {"auto_episode", "auto_episode_sum", "auto_episode_summary", "episode_note", "ambient_episode_note"}:
        return "【已确认群事件】"
    if name == "teach":
        return "【用户明确教导】"
    return "【相关群内记忆】"


def format_memory_blocks(hits: list[dict[str, Any]], *, max_len: int) -> str:
    """按来源分块渲染已召回记忆；总条数由上游 top_k 控制。"""
    grouped: dict[str, list[str]] = {}
    seen: set[str] = set()
    for item in hits:
        content = sanitize_prompt_block(str(item.get("content") or ""), max_len=max_len)
        if not content or content in seen:
            continue
        seen.add(content)
        section = memory_source_section(str(item.get("source") or ""))
        grouped.setdefault(section, []).append(content)
    order = ("【用户明确教导】", "【已确认群事件】", "【相关 IP 知识】", "【相关群内记忆】")
    blocks: list[str] = []
    for section in order:
        entries = grouped.get(section) or []
        if not entries:
            continue
        qualifier = "仅在当前话题相关时参考，不得覆盖核心人设。"
        blocks.append(f"{section} — {qualifier}\n" + "\n".join(f"- {entry}" for entry in entries))
    return "\n\n".join(blocks)


def _ambient_episode_note_hits(
    turns: list[LlmChatTurn],
    *,
    query_text: str,
    max_len: int,
) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    seen: set[str] = set()
    for turn in turns:
        if turn.role != "user":
            continue
        raw = (turn.content or "").strip()
        if classify_memory_candidate(raw) != "episode_note":
            continue
        note = normalize_episode_note(raw, max_len=max_len)
        if not note or note in seen:
            continue
        seen.add(note)
        score = memory_relevance_score(query_text, keywords=note, content=note)
        if score <= 0:
            continue
        candidates.append({"score": score, "content": note, "source": "ambient_episode_note"})
    candidates.sort(key=lambda item: int(item.get("score") or 0), reverse=True)
    return candidates


def _is_current_turn_auto_episode_echo(query_text: str, content: str) -> bool:
    query = "".join(char for char in str(query_text or "") if char.isalnum())
    note = "".join(char for char in str(content or "") if char.isalnum())
    return len(query) >= 6 and query == note


async def enrich_system_with_memory_context(
    system_prompt: str,
    *,
    bot_id: int,
    group_id: int | None,
    query_text: str,
    cfg: LlmConfig | None = None,
    allow_persistent_memory: bool = True,
) -> MemoryInjectionResult:
    c = cfg or get_llm_config()
    empty_trace = {"hit_count": 0, "sources": [], "entries": []}
    if not allow_persistent_memory:
        return MemoryInjectionResult(
            system_prompt=system_prompt,
            trace={**empty_trace, "skipped_short_social_turn": True},
        )
    plan = plan_memory_retrieval(query_text)
    if not plan.need_persistent:
        return MemoryInjectionResult(
            system_prompt=system_prompt,
            trace={
                **empty_trace,
                "skipped_unneeded_turn": True,
                "memory_plan": plan.model_dump(mode="json"),
            },
        )
    if not can_read_persistent_memory(c) or not c.llm_memory_rag_enabled:
        return MemoryInjectionResult(system_prompt=system_prompt, trace=empty_trace)
    hits = await retrieve_memory_hits(bot_id, group_id, query_text, cfg=c)
    skipped_current_turn_echoes = 0
    filtered_hits: list[dict[str, Any]] = []
    for item in hits:
        source = str(item.get("source") or "").strip()
        content = str(item.get("content") or "").strip()
        if source == "auto_episode" and _is_current_turn_auto_episode_echo(query_text, content):
            skipped_current_turn_echoes += 1
            continue
        filtered_hits.append(item)
    hits = filtered_hits
    top_k = max(1, min(int(c.llm_memory_rag_top_k), 8))
    min_score = effective_memory_rag_min_score(c)
    # 仅在持久记忆无命中时用 ambient 补，避免硬凑满 3 条噪声
    if group_id is not None and not hits:
        ambient = await list_group_ambient_messages(bot_id, group_id, limit=12, cfg=c)
        for hit in _ambient_episode_note_hits(
            ambient,
            query_text=query_text,
            max_len=c.llm_memory_content_max_len,
        ):
            if int(hit.get("score") or 0) < min_score:
                continue
            content = str(hit.get("content") or "").strip()
            if _is_current_turn_auto_episode_echo(query_text, content):
                skipped_current_turn_echoes += 1
                continue
            if any(str(item.get("content") or "").strip() == content for item in hits):
                continue
            hits.append(hit)
            if len(hits) >= top_k:
                break
    lines = [
        sanitize_prompt_block(str(item.get("content") or ""), max_len=c.llm_memory_content_max_len) for item in hits
    ]
    lines = [line for line in lines if line]
    trace = {
        "hit_count": len(lines),
        "retrieve_mode": vector_retrieve_mode(c),
        "sources": sorted({
            str(item.get("source") or "").strip() or "memory" for item in hits if str(item.get("content") or "").strip()
        }),
        "entries": [
            {
                "source": str(item.get("source") or "").strip() or "memory",
                "score": int(item.get("score") or 0),
                "content": str(item.get("content") or "").strip()[:120],
            }
            for item in hits
            if str(item.get("content") or "").strip()
        ],
        "skipped_current_turn_echoes": skipped_current_turn_echoes,
        "memory_plan": plan.model_dump(mode="json"),
    }
    from pallas.product.llm.knowledge.embedding_client import embedding_capability_trace

    trace.update(embedding_capability_trace(c))
    try:
        from pallas.product.llm.memory_rag_metrics import record_memory_rag_query_result

        if lines:
            record_memory_rag_query_result(
                hit=True,
                documents=[
                    (
                        str(item.get("content") or "").strip()[:40]
                        or str(item.get("source") or "").strip()
                        or "memory",
                        str(item.get("source") or "").strip() or "memory",
                    )
                    for item in hits
                    if str(item.get("content") or "").strip()
                ],
            )
        else:
            record_memory_rag_query_result(hit=False)
    except Exception:
        pass
    if not lines:
        return MemoryInjectionResult(system_prompt=system_prompt, trace=trace)
    block = format_memory_blocks(hits, max_len=c.llm_memory_content_max_len)
    if not block:
        return MemoryInjectionResult(system_prompt=system_prompt, trace=trace)
    base = (system_prompt or "").rstrip()
    prompt = f"{base}\n\n{block}" if base else block
    return MemoryInjectionResult(system_prompt=prompt, trace=trace)


async def append_memory_context(
    system_prompt: str,
    *,
    bot_id: int,
    group_id: int | None,
    query_text: str,
    cfg: LlmConfig | None = None,
) -> str:
    result = await enrich_system_with_memory_context(
        system_prompt,
        bot_id=bot_id,
        group_id=group_id,
        query_text=query_text,
        cfg=cfg,
    )
    return result.system_prompt


async def enrich_system_with_relationship_context(
    system_prompt: str,
    *,
    bot_id: int,
    group_id: int | None,
    user_id: int,
    cfg: LlmConfig | None = None,
    include_fallback: bool = True,
) -> RelationshipInjectionResult:
    c = cfg or get_llm_config()
    empty_trace = {"hit_count": 0, "sources": [], "entries": [], "fallback": False}
    if not can_read_persistent_memory(c) or not c.llm_relationship_notes_enabled or not user_id:
        return RelationshipInjectionResult(system_prompt=system_prompt, trace=empty_trace)
    profile: RelationshipProfile | None = await retrieve_relationship_profile(bot_id, group_id, user_id, cfg=c)
    lines: list[str] = []
    sources: list[str] = []
    entries: list[dict[str, str]] = []
    fallback = False
    preferred_name = ""
    if profile is not None and profile.has_facts:
        safe = sanitize_prompt_block(profile.content, max_len=c.llm_relationship_content_max_len)
        if safe:
            view = parse_relationship_fact_view(safe)
            preferred_name = view.preferred_name
            lines.extend(f"- {item}" for item in view.facts)
            lines.extend(f"- {hint}" for hint in build_relationship_guidance_lines(view))
            if lines:
                sources.append("relationship_note")
                entries.append({"source": "relationship_note", "content": safe[:120]})
    affinity = float(profile.affinity) if profile is not None else 0.0
    if affinity != 0.0:
        hint = "据此自然调整对你的热情/冷淡程度，不刻意讨好也不无故冷漠。"
        lines.append(f"- 好感度：{affinity_level(affinity)}（{affinity:+.2f}）→ {hint}")
        sources.append("relationship_affinity")
        entries.append({"source": "relationship_affinity", "content": affinity_level(affinity)})
    if not lines and include_fallback:
        lines.append(f"- {_RELATIONSHIP_FALLBACK}")
        sources.append("relationship_fallback")
        entries.append({"source": "relationship_fallback", "content": _RELATIONSHIP_FALLBACK[:120]})
        fallback = True
    if not lines:
        return RelationshipInjectionResult(system_prompt=system_prompt, trace=empty_trace)
    block = f"【与当前对话者的关系备注 — {_RELATIONSHIP_PRIORITY_HINT}】\n" + "\n".join(lines)
    base = (system_prompt or "").rstrip()
    prompt = f"{base}\n\n{block}" if base else block
    hit_count = 0 if fallback else 1
    note_source = str(profile.source or "").strip() if profile is not None else ""
    warmth_delta = float(profile.warmth_delta) if profile is not None else 0.0
    assertiveness_delta = float(profile.assertiveness_delta) if profile is not None else 0.0
    trace = {
        "hit_count": hit_count,
        "sources": sources,
        "entries": entries,
        "fallback": fallback,
        "affinity": affinity,
        "note_source": note_source or ("fallback" if fallback else ""),
        "preferred_name": preferred_name,
        "warmth_delta": warmth_delta,
        "assertiveness_delta": assertiveness_delta,
    }
    logger.debug(
        "Relationship injection for bot [{}], group [{}], and user [{}] had hit [{}], fallback [{}], note source [{}], "
        "warmth delta [{}], and assertiveness delta [{}]",
        bot_id,
        group_id,
        user_id,
        hit_count,
        fallback,
        trace["note_source"],
        warmth_delta,
        assertiveness_delta,
    )
    return RelationshipInjectionResult(system_prompt=prompt, trace=trace)


async def append_relationship_context(
    system_prompt: str,
    *,
    bot_id: int,
    group_id: int | None,
    user_id: int,
    cfg: LlmConfig | None = None,
) -> str:
    """把当前说话人的稳定关系备注追加到 system prompt（高门槛层，单条）。"""
    result = await enrich_system_with_relationship_context(
        system_prompt,
        bot_id=bot_id,
        group_id=group_id,
        user_id=user_id,
        cfg=cfg,
    )
    return result.system_prompt


async def enrich_system_with_person_facts(
    system_prompt: str,
    *,
    bot_id: int,
    group_id: int | None,
    user_id: int,
    cfg: LlmConfig | None = None,
) -> PersonFactsInjectionResult:
    if not group_id or not user_id:
        return PersonFactsInjectionResult(system_prompt=system_prompt)
    facts = retrieve_person_facts_for_prompt(
        bot_id=bot_id,
        group_id=group_id,
        user_id=user_id,
    )
    if not facts:
        return PersonFactsInjectionResult(system_prompt=system_prompt)
    block = "【当前对话者的稳定偏好 — 仅供参考】\n" + "\n".join(f"- {fact}" for fact in facts)
    base = (system_prompt or "").rstrip()
    return PersonFactsInjectionResult(
        system_prompt=f"{base}\n\n{block}" if base else block,
        trace={"hit_count": len(facts), "sources": ["person_fact"]},
    )
