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

    group_clause = ""
    params: dict[str, int] = {"lim": max(limit * 4, limit)}
    if scope == "group" and group_id is not None:
        group_clause = "AND a.group_id = :group_id"
        params["group_id"] = int(group_id)

    async with get_session(read_only=True) as session:
        rows = (
            (
                await session.execute(
                    text(
                        f"""
                    SELECT c.id AS context_id, c.keywords, SUM(a.count) AS score
                    FROM context c
                    INNER JOIN context_answer a ON a.context_id = c.id
                    WHERE 1=1 {group_clause}
                    GROUP BY c.id, c.keywords
                    ORDER BY score DESC, c.keywords ASC
                    LIMIT :lim
                    """
                    ),
                    params,
                )
            )
            .mappings()
            .all()
        )

        out: list[dict[str, Any]] = []
        for row in rows:
            label = plain_message_text(str(row["keywords"] or ""))
            if not label:
                continue
            ctx_id = int(row["context_id"])
            answer_params: dict[str, int] = {
                "context_id": ctx_id,
                "ans_lim": answers_per_keyword,
            }
            ans_group_clause = ""
            if scope == "group" and group_id is not None:
                ans_group_clause = "AND a.group_id = :group_id"
                answer_params["group_id"] = int(group_id)
            answer_rows = (
                (
                    await session.execute(
                        text(
                            f"""
                        SELECT a.keywords AS answer_keywords, a.count,
                               (
                                   SELECT m.message
                                   FROM context_answer_message m
                                   WHERE m.answer_id = a.id
                                   ORDER BY m.id ASC
                                   LIMIT 1
                               ) AS message
                        FROM context_answer a
                        WHERE a.context_id = :context_id {ans_group_clause}
                        ORDER BY a.count DESC, a.keywords ASC
                        LIMIT :ans_lim
                        """
                        ),
                        answer_params,
                    )
                )
                .mappings()
                .all()
            )
            answers = build_hot_answers(answer_rows)
            if not answers:
                continue
            out.append({"keywords": label, "score": int(row["score"] or 0), "answers": answers})
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
    from pydantic import BaseModel, Field

    from pallas.core.foundation.db.modules import Answer, Context

    # Beanie 2.x：project() 只接受单一 projection model，不能传多个字段表达式
    class _ContextHotProjection(BaseModel):
        keywords: str = ""
        answers: list[Answer] = Field(default_factory=list)

    contexts = await Context.find_all().project(_ContextHotProjection).to_list()
    buckets: dict[str, dict[str, Any]] = {}
    for ctx in contexts:
        label = plain_message_text(ctx.keywords)
        if not label:
            continue
        bucket = buckets.setdefault(label, {"keywords": label, "score": 0, "answer_rows": []})
        for ans in ctx.answers or []:
            if scope == "group" and group_id is not None and int(ans.group_id) != int(group_id):
                continue
            bucket["score"] += int(ans.count or 0)
            bucket["answer_rows"].append({
                "answer_keywords": ans.keywords,
                "count": int(ans.count or 0),
                "message": pick_answer_message(ans.messages, ans.keywords),
            })

    ranked = sorted(buckets.values(), key=lambda row: (-int(row["score"]), str(row["keywords"])))
    out: list[dict[str, Any]] = []
    for row in ranked[:limit]:
        answer_rows = sorted(
            row["answer_rows"],
            key=lambda ans: (-int(ans["count"]), str(ans["answer_keywords"])),
        )[:answers_per_keyword]
        answers = build_hot_answers(answer_rows)
        if not answers:
            continue
        out.append({"keywords": row["keywords"], "score": int(row["score"]), "answers": answers})
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
