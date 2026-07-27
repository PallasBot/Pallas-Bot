"""本机语料热词聚合。"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import text

from pallas.core.foundation.db import get_db_backend
from pallas.product.corpus.text_util import plain_message_text


def local_corpus_hot_as_of() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def build_local_corpus_hot_payload(
    items: list[dict[str, Any]],
    *,
    as_of: str | None = None,
) -> dict[str, Any]:
    return {
        "mode": "pool",
        "period": "day",
        "window_sec": 0,
        "as_of": as_of or local_corpus_hot_as_of(),
        "items": items,
    }


async def aggregate_local_hot_keywords(
    *,
    scope: str = "global",
    group_id: int | None = None,
    limit: int = 40,
    answers_per_keyword: int = 3,
) -> list[dict[str, Any]]:
    scope_norm = scope if scope in ("global", "group") else "global"
    limit = max(5, min(int(limit), 80))
    answers_per_keyword = max(1, min(int(answers_per_keyword), 8))
    backend = get_db_backend()
    if backend == "postgresql":
        return await aggregate_local_hot_keywords_pg(
            scope=scope_norm,
            group_id=group_id,
            limit=limit,
            answers_per_keyword=answers_per_keyword,
        )
    if backend == "mongodb":
        return await aggregate_local_hot_keywords_mongo(
            scope=scope_norm,
            group_id=group_id,
            limit=limit,
            answers_per_keyword=answers_per_keyword,
        )
    return []


async def aggregate_local_hot_keywords_pg(
    *,
    scope: str,
    group_id: int | None,
    limit: int,
    answers_per_keyword: int,
) -> list[dict[str, Any]]:
    from pallas.core.foundation.db.repository_pg import get_session

    # 一次 SQL 取 top 词条 + 每条 top 回复，避免 N+1
    group_clause = ""
    ans_group_clause = ""
    params: dict[str, int] = {
        "lim": max(limit * 4, limit),
        "ans_lim": answers_per_keyword,
    }
    if scope == "group" and group_id is not None:
        group_clause = "AND a.group_id = :group_id"
        ans_group_clause = "AND a.group_id = :group_id"
        params["group_id"] = int(group_id)

    sql = f"""
WITH top_ctx AS (
    SELECT c.id AS context_id, c.keywords, SUM(a.count) AS score
    FROM context c
    INNER JOIN context_answer a ON a.context_id = c.id
    WHERE 1=1 {group_clause}
    GROUP BY c.id, c.keywords
    ORDER BY score DESC, c.keywords ASC
    LIMIT :lim
), ranked AS (
    SELECT
        tc.context_id,
        tc.keywords,
        tc.score,
        a.keywords AS answer_keywords,
        a.count AS answer_count,
        a.id AS answer_id,
        ROW_NUMBER() OVER (
            PARTITION BY tc.context_id
            ORDER BY a.count DESC, a.keywords ASC
        ) AS rn
    FROM top_ctx tc
    INNER JOIN context_answer a ON a.context_id = tc.context_id
    WHERE 1=1 {ans_group_clause}
)
SELECT
    r.context_id,
    r.keywords,
    r.score,
    r.answer_keywords,
    r.answer_count AS count,
    m.message
FROM ranked r
LEFT JOIN LATERAL (
    SELECT message
    FROM context_answer_message msg
    WHERE msg.answer_id = r.answer_id
    ORDER BY msg.id ASC
    LIMIT 1
) m ON TRUE
WHERE r.rn <= :ans_lim
ORDER BY r.score DESC, r.keywords ASC, r.rn ASC
"""

    async with get_session(read_only=True) as session:
        rows = (await session.execute(text(sql), params)).mappings().all()

    by_ctx: dict[int, dict[str, Any]] = {}
    order: list[int] = []
    for row in rows:
        ctx_id = int(row["context_id"])
        bucket = by_ctx.get(ctx_id)
        if bucket is None:
            label = plain_message_text(str(row["keywords"] or ""))
            if not label:
                continue
            bucket = {"keywords": label, "score": int(row["score"] or 0), "answer_rows": []}
            by_ctx[ctx_id] = bucket
            order.append(ctx_id)
        bucket["answer_rows"].append({
            "answer_keywords": row.get("answer_keywords"),
            "count": int(row.get("count") or 0),
            "message": row.get("message"),
        })

    out: list[dict[str, Any]] = []
    for ctx_id in order:
        bucket = by_ctx[ctx_id]
        answers = build_hot_answers(bucket["answer_rows"])
        if not answers:
            continue
        out.append({"keywords": bucket["keywords"], "score": int(bucket["score"]), "answers": answers})
        if len(out) >= limit:
            break
    return out


async def aggregate_local_hot_keywords_mongo(
    *,
    scope: str,
    group_id: int | None,
    limit: int,
    answers_per_keyword: int,
) -> list[dict[str, Any]]:
    from pallas.core.foundation.db.modules import Context

    # 库内聚合取 top 词条，避免 find_all 整表拉入内存
    overfetch = max(limit * 4, limit)
    score_pipeline: list[dict[str, Any]] = [{"$unwind": "$answers"}]
    if scope == "group" and group_id is not None:
        score_pipeline.append({"$match": {"answers.group_id": int(group_id)}})
    score_pipeline.extend([
        {
            "$group": {
                "_id": "$keywords",
                "score": {"$sum": {"$ifNull": ["$answers.count", 0]}},
            }
        },
        {"$sort": {"score": -1, "_id": 1}},
        {"$limit": overfetch},
    ])
    score_rows = await Context.get_motor_collection().aggregate(score_pipeline).to_list(overfetch)
    if not score_rows:
        return []

    raw_keys = [str(r.get("_id") or "") for r in score_rows if str(r.get("_id") or "").strip()]
    if not raw_keys:
        return []

    answer_pipeline: list[dict[str, Any]] = [
        {"$match": {"keywords": {"$in": raw_keys}}},
        {"$unwind": "$answers"},
    ]
    if scope == "group" and group_id is not None:
        answer_pipeline.append({"$match": {"answers.group_id": int(group_id)}})
    answer_pipeline.extend([
        {
            "$project": {
                "keywords": 1,
                "answer_keywords": "$answers.keywords",
                "count": {"$ifNull": ["$answers.count", 0]},
                "messages": "$answers.messages",
            }
        },
        {"$sort": {"keywords": 1, "count": -1, "answer_keywords": 1}},
        {
            "$group": {
                "_id": "$keywords",
                "answer_rows": {
                    "$push": {
                        "answer_keywords": "$answer_keywords",
                        "count": "$count",
                        "messages": "$messages",
                    }
                },
            }
        },
    ])
    answer_docs = await Context.get_motor_collection().aggregate(answer_pipeline).to_list(overfetch)
    answers_by_raw: dict[str, list[dict[str, Any]]] = {
        str(doc.get("_id") or ""): list(doc.get("answer_rows") or []) for doc in answer_docs
    }

    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in score_rows:
        raw = str(row.get("_id") or "")
        label = plain_message_text(raw)
        if not label or label in seen:
            continue
        seen.add(label)
        answer_rows_raw = answers_by_raw.get(raw) or []
        trimmed = [
            {
                "answer_keywords": ans.get("answer_keywords"),
                "count": int(ans.get("count") or 0),
                "message": pick_answer_message(ans.get("messages"), ans.get("answer_keywords") or ""),
            }
            for ans in answer_rows_raw[:answers_per_keyword]
        ]
        answers = build_hot_answers(trimmed)
        if not answers:
            continue
        out.append({"keywords": label, "score": int(row.get("score") or 0), "answers": answers})
        if len(out) >= limit:
            break
    return out


def pick_answer_message(messages: list[str] | None, fallback: str) -> str:
    for raw in messages or []:
        text = plain_message_text(str(raw))
        if text:
            return text
    return plain_message_text(str(fallback or ""))


def build_hot_answers(answer_rows: list[Any]) -> list[dict[str, Any]]:
    answers: list[dict[str, Any]] = []
    for ans in answer_rows:
        message = plain_message_text(str(ans.get("message") or ""))
        if not message:
            message = plain_message_text(str(ans.get("answer_keywords") or ""))
        if not message:
            continue
        if len(message) > 120:
            message = message[:117] + "…"
        answers.append({
            "answer_keywords": str(ans.get("answer_keywords") or ""),
            "message": message,
            "count": int(ans.get("count") or 0),
        })
    return answers


async def build_corpus_hot_snapshot_items(*, limit: int = 40) -> list[dict[str, Any]]:
    rows = await aggregate_local_hot_keywords(scope="global", limit=limit, answers_per_keyword=1)
    return [{"keywords": row["keywords"], "score": int(row["score"])} for row in rows if row.get("keywords")]
