"""记忆图谱：从文本/Episode 用 LLM 抽取实体与边。"""

from __future__ import annotations

import time
from typing import Any

from nonebot import logger

from pallas.product.llm.config import get_llm_config
from pallas.product.llm.inference_params import task_token_budget
from pallas.product.llm.memory.graph.json_parse import parse_llm_json
from pallas.product.llm.memory.graph.scope import make_scope_key
from pallas.product.llm.memory.graph.store import is_memory_graph_store_available, upsert_edge, upsert_entity
from pallas.product.llm.memory.rate_limit import WriteCooldown
from pallas.product.persona.prompt_guard import sanitize_prompt_literal

_EXTRACT_SYSTEM = """你是群聊记忆抽取助手。从给定文本中提取实体与关系，只输出 JSON，不要解释。

输出键名使用简写：
- entities: 实体数组，每项含 n(名称)、s(摘要≤50字)、t(标签数组，最多5个)、u(可选 user_id)
- edges: 关系数组，每项含 src(主语名)、tgt(宾语名)、f(事实描述)

规则：
1. 只依据原文明确信息，禁止臆造。
2. 人物、地点、话题、事件、概念均可作为实体。
3. 关系事实要简洁完整。
4. 输出示例：
{"entities":[{"n":"小明","s":"群成员","t":["人"],"u":123}],"edges":[{"src":"小明","tgt":"篮球","f":"喜欢打篮球"}]}
"""

_BATCH_EXTRACT_SYSTEM = """你是群聊记忆抽取助手。给定 [count] 组独立文本，对每组输出一个抽取结果，
最终只输出一个严格 JSON 数组，数组长度等于 [count]，按 [0],[1],[2]… 下标顺序与输入一一对应。

每个元素与单组抽取格式相同：
- entities: 实体数组，每项含 n(名称)、s(摘要≤50字)、t(标签数组，最多5个)、u(可选 user_id)
- edges: 关系数组，每项含 src(主语名)、tgt(宾语名)、f(事实描述)

规则：
1. 只依据各自文本中的明确信息，禁止臆造。
2. 人物、地点、话题、事件、概念均可作为实体。
3. 关系事实要简洁完整。
4. 每组没有值得抽取的内容时输出空对象 {{"entities":[],"edges":[]}}，不要为对齐而臆造。

输出示例（2 组，下标 [0] 与 [1] 分别对应第 1、2 组）：
[{{"entities":[{{"n":"小明","s":"群成员","t":["人"],"u":123}}],"edges":[{{"src":"小明","tgt":"篮球","f":"喜欢打篮球"}}]}},{{"entities":[],"edges":[]}}]
"""

_EXTRACT_USER = """scope={scope_key}
待抽取文本：
{text}
请输出 JSON。"""

_BATCH_EXTRACT_USER = """scope={scope_key}
待抽取文本（[下标] 与输入顺序对应）：
{items}
请按 [0],[1],[2]… 输出严格 JSON 数组。"""

_EXTRACT_EPISODE_TEXT_LIMIT = 800
# 写入后自动抽取属于后台富化而非热路径，冷却 5 分钟 + 每日预算闸控制调用量
_EXTRACT_COOLDOWN_SEC = 300

_extract_cooldown = WriteCooldown()
_last_extract_sig: dict[tuple[int, int], str] = {}
_graph_extract_budget_day = ""
_graph_extract_daily_budget_used = 0


def clear_extract_state_for_tests() -> None:
    _extract_cooldown.clear()
    _last_extract_sig.clear()
    global _graph_extract_budget_day, _graph_extract_daily_budget_used
    _graph_extract_budget_day = ""
    _graph_extract_daily_budget_used = 0


def _graph_extract_budget_ok() -> bool:
    limit = int(get_llm_config().llm_memory_graph_extract_daily_budget)
    if limit <= 0:
        return True
    global _graph_extract_budget_day, _graph_extract_daily_budget_used
    today = time.strftime("%Y-%m-%d")
    if _graph_extract_budget_day != today:
        _graph_extract_budget_day = today
        _graph_extract_daily_budget_used = 0
    return _graph_extract_daily_budget_used < limit


def _reserve_graph_extract_budget(count: int = 1) -> bool:
    count = max(1, int(count))
    limit = int(get_llm_config().llm_memory_graph_extract_daily_budget)
    if limit <= 0:
        return True
    global _graph_extract_budget_day, _graph_extract_daily_budget_used
    today = time.strftime("%Y-%m-%d")
    if _graph_extract_budget_day != today:
        _graph_extract_budget_day = today
        _graph_extract_daily_budget_used = 0
    if _graph_extract_daily_budget_used + count > limit:
        return False
    _graph_extract_daily_budget_used += count
    return True


def _resolve_extract_task_and_model() -> tuple[str, str]:
    from pallas.product.llm.providers_store import resolve_endpoint_for_task

    cfg = get_llm_config()
    for task in ("memory_extract", "llm_chat"):
        endpoint = resolve_endpoint_for_task(task)
        if endpoint is not None and endpoint.model:
            return task, endpoint.model
    return "llm_chat", str(cfg.llm_model or "").strip()


def _call_inputs_for_task() -> tuple[str, str, dict[str, Any]]:
    task, model = _resolve_extract_task_and_model()
    if not model:
        raise RuntimeError("no llm model for memory extract")
    return task, model, {"temperature": 0.2, "num_predict": task_token_budget("memory_graph_extract")}


async def _call_extract_llm(text: str, *, scope_key: str) -> str:
    from pallas.product.llm.provider_client import complete_chat_message

    task, model, options = _call_inputs_for_task()
    user = _EXTRACT_USER.format(scope_key=scope_key, text=text[:4000])
    message = await complete_chat_message(
        [
            {"role": "system", "content": _EXTRACT_SYSTEM},
            {"role": "user", "content": user},
        ],
        model=model,
        options=options,
        task=task,
    )
    return str(message.get("content") or "").strip()


async def _call_extract_batch(items: list[str], *, scope_key: str) -> str:
    from pallas.product.llm.provider_client import complete_chat_message

    task, model, options = _call_inputs_for_task()
    prompt_items = [f"[{index}] {text[:_EXTRACT_EPISODE_TEXT_LIMIT]}" for index, text in enumerate(items)]
    user = _BATCH_EXTRACT_USER.format(scope_key=scope_key, items="\n".join(prompt_items))
    message = await complete_chat_message(
        [
            {"role": "system", "content": _BATCH_EXTRACT_SYSTEM.replace("[count]", str(len(items)))},
            {"role": "user", "content": user},
        ],
        model=model,
        options={**options, "num_predict": task_token_budget("memory_graph_extract") * len(items)},
        task=task,
    )
    return str(message.get("content") or "").strip()


def _kind_from_tags(tags: list[str], user_id: int | None) -> str:
    lowered = {t.casefold() for t in tags}
    if user_id is not None or "speaker" in lowered or "人" in tags or "person" in lowered:
        return "person"
    if "地点" in tags or "place" in lowered or "location" in lowered:
        return "place"
    if "事件" in tags or "event" in lowered:
        return "event"
    return "concept"


async def _apply_extraction_payload(
    *,
    bot_id: int,
    group_id: int | None,
    payload: dict[str, Any],
    episode_id: str | None = None,
) -> tuple[int, int]:
    """把单组抽取结果（entities/edges）upsert 到图谱，返回 (entities_n, edges_n)。"""
    entities_raw = payload.get("entities") if isinstance(payload.get("entities"), list) else []
    edges_raw = payload.get("edges") if isinstance(payload.get("edges"), list) else []
    name_to_id: dict[str, int] = {}
    entities_n = 0
    edges_n = 0

    for item in entities_raw:
        if not isinstance(item, dict):
            continue
        name = sanitize_prompt_literal(str(item.get("n") or item.get("name") or ""), max_len=64)
        if not name:
            continue
        summary = sanitize_prompt_literal(str(item.get("s") or item.get("summary") or ""), max_len=120) or ""
        tags_raw = item.get("t") if isinstance(item.get("t"), list) else item.get("tags")
        tags = [sanitize_prompt_literal(str(t), max_len=32) for t in (tags_raw or [])]
        tags = [t for t in tags if t][:5]
        user_id = None
        if item.get("u") is not None:
            try:
                user_id = int(item.get("u"))
            except (TypeError, ValueError):
                user_id = None
        ent = await upsert_entity(
            bot_id=bot_id,
            group_id=group_id,
            name=name,
            summary=summary,
            tags=tags,
            kind=_kind_from_tags(tags, user_id),
            user_id=user_id,
            source="extract",
        )
        if ent:
            entities_n += 1
            name_to_id[name] = int(ent["entity_id"])
            name_to_id[name.casefold()] = int(ent["entity_id"])

    episode_ids = [str(episode_id)] if episode_id else None
    for item in edges_raw:
        if not isinstance(item, dict):
            continue
        src = sanitize_prompt_literal(str(item.get("src") or ""), max_len=64)
        tgt = sanitize_prompt_literal(str(item.get("tgt") or ""), max_len=64)
        fact = sanitize_prompt_literal(str(item.get("f") or item.get("fact") or ""), max_len=500)
        if not src or not tgt or not fact:
            continue
        src_id = name_to_id.get(src) or name_to_id.get(src.casefold())
        tgt_id = name_to_id.get(tgt) or name_to_id.get(tgt.casefold())
        if not src_id:
            ent = await upsert_entity(bot_id=bot_id, group_id=group_id, name=src, source="extract")
            src_id = int(ent["entity_id"]) if ent else 0
            if src_id:
                name_to_id[src] = src_id
                entities_n += 1
        if not tgt_id:
            ent = await upsert_entity(bot_id=bot_id, group_id=group_id, name=tgt, source="extract")
            tgt_id = int(ent["entity_id"]) if ent else 0
            if tgt_id:
                name_to_id[tgt] = tgt_id
                entities_n += 1
        if src_id <= 0 or tgt_id <= 0:
            continue
        edge = await upsert_edge(
            bot_id=bot_id,
            group_id=group_id,
            fact=fact,
            source_entity_id=src_id,
            target_entity_id=tgt_id,
            episode_ids=episode_ids,
            source="extract",
        )
        if edge:
            edges_n += 1

    return entities_n, edges_n


async def extract_from_text(
    *,
    bot_id: int,
    group_id: int | None,
    text: str,
    episode_id: str | None = None,
) -> dict[str, Any]:
    """对单段文本做 LLM 抽取并 upsert 实体/边。"""
    raw_text = str(text or "").strip()
    if not raw_text:
        return {"entities_upserted": 0, "edges_upserted": 0, "error": "empty text"}
    if not _reserve_graph_extract_budget():
        return {"entities_upserted": 0, "edges_upserted": 0, "error": "daily budget exhausted"}
    if not is_memory_graph_store_available():
        return {"entities_upserted": 0, "edges_upserted": 0, "error": "store unavailable"}

    scope_key = make_scope_key(bot_id=bot_id, group_id=group_id)
    try:
        raw = await _call_extract_llm(raw_text, scope_key=scope_key)
        payload = parse_llm_json(raw)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Memory graph LLM extraction failed for scope [{}]: [{}]", scope_key, exc)
        return {"entities_upserted": 0, "edges_upserted": 0, "error": str(exc)}

    if not isinstance(payload, dict):
        return {"entities_upserted": 0, "edges_upserted": 0, "raw": raw, "error": "json not object"}

    entities_n, edges_n = await _apply_extraction_payload(
        bot_id=bot_id,
        group_id=group_id,
        payload=payload,
        episode_id=episode_id,
    )
    return {"entities_upserted": entities_n, "edges_upserted": edges_n, "raw": raw}


def _extract_item_reliable(payload: Any) -> bool:
    """判断某个批量抽取项是否有效（含实体或关系，或明确空结果）。"""
    if not isinstance(payload, dict):
        return False
    entities = payload.get("entities")
    edges = payload.get("edges")
    return isinstance(entities, list) and isinstance(edges, list)


def _batch_extract_reliable(parsed: list[Any], expected: int) -> bool:
    """整批是否可靠：数量对齐且有效项过半，否则按序应用可能错位。"""
    if len(parsed) != expected or not parsed:
        return False
    ok = sum(1 for item in parsed if _extract_item_reliable(item))
    return ok >= max(1, (expected + 1) // 2)


async def extract_from_episodes(
    *,
    bot_id: int,
    group_id: int | None,
    limit: int = 20,
) -> dict[str, Any]:
    """批量对最近 episodes 做抽取：一次 LLM 调用产出多个结果（参照语义风格批量范式）。"""
    from pallas.product.llm.memory.graph.service import list_episodes

    if not is_memory_graph_store_available():
        return {"episodes": 0, "entities_upserted": 0, "edges_upserted": 0, "error": "store unavailable"}

    max_n = max(1, min(int(limit), 50))
    episodes = await list_episodes(bot_id=bot_id, group_id=group_id, limit=max_n)
    targets: list[tuple[int | None, str, str | None]] = []
    for ep in episodes:
        content = str(ep.get("content") or "").strip()
        if not content:
            continue
        ep_group_id = int(ep.get("group_id") or group_id or 0) or group_id
        targets.append((ep_group_id, content, str(ep.get("id") or "") or None))

    total_entities = 0
    total_edges = 0
    errors: list[str] = []
    if targets:
        scope_key = make_scope_key(bot_id=bot_id, group_id=group_id)
        if not _reserve_graph_extract_budget(len(targets)):
            return {
                "episodes": len(targets),
                "entities_upserted": 0,
                "edges_upserted": 0,
                "error": "daily budget exhausted",
            }
        try:
            raw = await _call_extract_batch([t[1] for t in targets], scope_key=scope_key)
            parsed = parse_llm_json(raw)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Memory graph batch extraction failed for scope [{}]: [{}]", scope_key, exc)
            errors.append(str(exc))
            parsed = []

        if isinstance(parsed, list) and _batch_extract_reliable(parsed, len(targets)):
            for (ep_group_id, _content, episode_id), payload in zip(targets, parsed, strict=True):
                entities_n, edges_n = await _apply_extraction_payload(
                    bot_id=bot_id,
                    group_id=ep_group_id,
                    payload=payload,
                    episode_id=episode_id,
                )
                total_entities += entities_n
                total_edges += edges_n
        else:
            errors.append("batch result unreliable")

    out: dict[str, Any] = {
        "episodes": len(targets),
        "entities_upserted": total_entities,
        "edges_upserted": total_edges,
    }
    if errors:
        out["error"] = "; ".join(errors[:5])
    return out


async def maybe_extract_after_episode_write(
    *,
    bot_id: int,
    group_id: int | None,
    text: str,
    episode_id: str | None = None,
) -> None:
    """写入 episode 后按配置可选触发抽取；带同文本去重与冷却抑制，失败仅 warning。"""
    try:
        cfg = get_llm_config()
        if not cfg.llm_memory_graph_extract_enabled or not cfg.llm_memory_graph_extract_on_write:
            return
        raw_text = str(text or "").strip()
        if not raw_text:
            return
        key = (int(bot_id), int(group_id or 0))
        if _last_extract_sig.get(key) == raw_text:
            return
        if not _graph_extract_budget_ok():
            return
        if not _extract_cooldown.ok(key, _EXTRACT_COOLDOWN_SEC):
            return
        result = await extract_from_text(
            bot_id=bot_id,
            group_id=group_id,
            text=raw_text,
            episode_id=episode_id,
        )
        if result.get("error"):
            logger.warning(
                "Memory graph extraction on write failed for bot [{}] and group [{}]: [{}]",
                bot_id,
                group_id,
                result.get("error"),
            )
            return
        _last_extract_sig[key] = raw_text
        _extract_cooldown.mark(key)
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "Memory graph extraction on write failed for bot [{}] and group [{}]: [{}]", bot_id, group_id, exc
        )
