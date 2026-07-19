"""语料污染判定与语料扫库。"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Literal

from nonebot import logger
from sqlalchemy import bindparam, text

CorpusContaminationGate = Literal[
    "learn",
    "feedback_meta",
    "output_chat_hard",
    "output_chat_soft",
    "output_polish_hard",
    "output_polish_soft",
]

CORPUS_LEARN_BLOCK_PHRASES: tuple[str, ...] = (
    "希望每个庆典",
    "庆典感满满",
    "谢谢您的陪伴",
    "今天也谢谢您的陪伴",
    "罗德岛的干员帕拉斯",
    "我是罗德岛的干员帕拉斯",
    "有啥好玩的事情想和我聊聊",
    "您还有什么想了解",
    "咱们聊聊最近的庆典",
    "庆典还在继续",
    "庆典上肯定",
    "有什么需要帮忙的记得告诉我",
    "随时为你效劳",
    "继续聊干员的事儿",
    "咱们继续聊干员",
    "为您服务",
)

CORPUS_LEARN_EXCLUDE_SUBSTR: tuple[str, ...] = ("流媒体解析bot",)

_UNSAFE_LEARN_TEXT_RE = re.compile(
    r"\[CQ:|(?:匹配|任务|请求).{0,12}(?:失败|异常)|积分不足|(?:我|你|他)操你妈|操你妈",
    re.IGNORECASE,
)


def match_unsafe_learn_text(text: str) -> str | None:
    """协议片段、插件回包与攻击性话术不得进入候选或学习链路。"""
    plain = str(text or "").strip()
    if not plain:
        return "empty"
    match = _UNSAFE_LEARN_TEXT_RE.search(plain)
    return match.group(0) if match else None


def is_llm_learning_safe(text: str) -> bool:
    """不受可配置语料清理开关影响的基础安全准入。"""
    return match_unsafe_learn_text(text) is None


FEEDBACK_META_BLOCK_PHRASES: tuple[str, ...] = (
    "因为",
    "通常",
    "一般来说",
    "总结一下",
    "首先",
)

CHAT_HARD_BLOCK_PHRASES: tuple[str, ...] = (
    "博士",
    "您",
    "继续聊",
    "想聊",
    "有什么想",
    "有什么可以",
    "换个话题",
    "聊点什么",
    "希望每个庆典",
    "庆典感满满",
    "为您服务",
    "谢谢您的陪伴",
)

CHAT_SOFT_RETRY_PHRASES: tuple[str, ...] = (
    "聊聊吗",
    "很高兴",
    "嘻嘻",
    "[嘻嘻]",
)

POLISH_LITE_HARD_BLOCK_PHRASES: tuple[str, ...] = (
    "继续聊",
    "希望每个庆典",
    "罗德岛的干员",
)

POLISH_LITE_SOFT_RETRY_PHRASES: tuple[str, ...] = ("换个话题",)


@dataclass(frozen=True, slots=True)
class CorpusContaminationHit:
    phrase: str
    gate: CorpusContaminationGate


def corpus_learn_guard_enabled() -> bool:
    from pallas.product.llm.config import get_llm_config

    return bool(get_llm_config().llm_corpus_learn_guard_enabled)


def corpus_cleanup_scheduled_enabled() -> bool:
    from pallas.product.llm.config import get_llm_config

    return bool(get_llm_config().llm_corpus_cleanup_scheduled_enabled)


def corpus_cleanup_interval_sec() -> int:
    from pallas.product.llm.config import get_llm_config

    return int(get_llm_config().llm_corpus_cleanup_interval_sec)


def corpus_cleanup_message_history_enabled() -> bool:
    from pallas.product.llm.config import get_llm_config

    return bool(get_llm_config().llm_corpus_cleanup_message_history_enabled)


def match_corpus_learn_block(text: str) -> CorpusContaminationHit | None:
    plain = str(text or "").strip()
    if not plain:
        return None
    if any(exclude in plain for exclude in CORPUS_LEARN_EXCLUDE_SUBSTR):
        return None
    for phrase in CORPUS_LEARN_BLOCK_PHRASES:
        if phrase in plain:
            return CorpusContaminationHit(phrase=phrase, gate="learn")
    return None


def match_feedback_meta_block(text: str) -> CorpusContaminationHit | None:
    plain = str(text or "").strip()
    if not plain:
        return None
    for phrase in FEEDBACK_META_BLOCK_PHRASES:
        if phrase in plain:
            return CorpusContaminationHit(phrase=phrase, gate="feedback_meta")
    return None


def is_corpus_learn_safe(text: str) -> bool:
    if not is_llm_learning_safe(text):
        return False
    if not corpus_learn_guard_enabled():
        return True
    return match_corpus_learn_block(text) is None


def is_expression_reference_safe(text: str) -> bool:
    """动态表达 / 语料收尾参考：挡庆典腔等间接污染。"""
    if not corpus_learn_guard_enabled():
        return True
    plain = str(text or "").strip()
    if not plain:
        return False
    if match_corpus_learn_block(plain) is not None:
        return False
    for phrase in CHAT_HARD_BLOCK_PHRASES:
        if phrase in plain:
            return False
    return True


def is_profiler_sample_safe(text: str) -> bool:
    """群 style profiler 样本：与语料学习门控一致。"""
    return is_corpus_learn_safe(text)


def is_profiler_answer_safe(answer: object) -> bool:
    messages = getattr(answer, "messages", None) or []
    samples = [str(item or "").strip() for item in messages if str(item or "").strip()]
    if samples:
        return all(is_profiler_sample_safe(item) for item in samples)
    keywords = str(getattr(answer, "keywords", "") or "").strip()
    if keywords and not is_profiler_sample_safe(keywords):
        return False
    return bool(samples or keywords)


def is_feedback_reply_collectable(text: str) -> bool:
    plain = str(text or "").strip()
    if not is_llm_learning_safe(plain):
        return False
    if match_feedback_meta_block(plain) is not None:
        return False
    return match_corpus_learn_block(plain) is None


def reject_corpus_learn_message(message: str, *, source: str = "") -> bool:
    if not corpus_learn_guard_enabled():
        return False
    hit = match_corpus_learn_block(message)
    if hit is None:
        return False
    preview = str(message or "").strip()
    if len(preview) > 80:
        preview = preview[:80] + "…"
    logger.debug("corpus learn guard blocked source={} phrase={} text={}", source, hit.phrase, preview)
    return True


def build_like_clause(column: str, phrases: tuple[str, ...], *, prefix: str) -> tuple[str, dict[str, str]]:
    parts: list[str] = []
    params: dict[str, str] = {}
    for index, phrase in enumerate(phrases):
        key = f"{prefix}{index}"
        parts.append(f"{column} LIKE :{key}")
        params[key] = f"%{phrase}%"
    return " OR ".join(parts), params


@dataclass(frozen=True, slots=True)
class CorpusCleanupReport:
    answer_message_candidates: int
    parent_answer_candidates: int
    message_candidates: int
    deleted_answer_messages: int
    deleted_empty_answers: int
    deleted_message_history: int


CorpusPgCleanupReport = CorpusCleanupReport


def build_mongo_substr_query(
    field: str,
    phrases: tuple[str, ...],
    excludes: tuple[str, ...] = (),
) -> dict[str, Any]:
    clauses: list[dict[str, Any]] = []
    if phrases:
        clauses.append({"$or": [{field: {"$regex": re.escape(phrase)}} for phrase in phrases]})
    clauses.extend({field: {"$not": {"$regex": re.escape(exclude)}}} for exclude in excludes)
    if not clauses:
        return {}
    if len(clauses) == 1:
        return clauses[0]
    return {"$and": clauses}


def prune_polluted_context_answers(answers: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], int, int]:
    removed_messages = 0
    removed_answers = 0
    kept: list[dict[str, Any]] = []
    for answer in answers:
        messages = [str(item) for item in (answer.get("messages") or [])]
        clean_messages = [item for item in messages if match_corpus_learn_block(item) is None]
        removed_messages += len(messages) - len(clean_messages)
        if clean_messages:
            if len(clean_messages) != len(messages):
                answer = dict(answer)
                answer["messages"] = clean_messages
            kept.append(answer)
        elif messages:
            removed_answers += 1
    return kept, removed_messages, removed_answers


async def run_corpus_contamination_cleanup(
    *,
    apply: bool,
    preview_limit: int = 20,
    clean_message_history: bool | None = None,
) -> CorpusCleanupReport:
    from pallas.core.foundation.db import is_mongodb_backend, is_postgresql_backend

    if is_postgresql_backend():
        return await run_pg_corpus_contamination_cleanup(
            apply=apply,
            preview_limit=preview_limit,
            clean_message_history=clean_message_history,
        )
    if is_mongodb_backend():
        return await run_mongo_corpus_contamination_cleanup(
            apply=apply,
            preview_limit=preview_limit,
            clean_message_history=clean_message_history,
        )
    return CorpusCleanupReport(0, 0, 0, 0, 0, 0)


async def run_mongo_corpus_contamination_cleanup(
    *,
    apply: bool,
    preview_limit: int = 20,
    clean_message_history: bool | None = None,
) -> CorpusCleanupReport:
    from pallas.core.foundation.db import init_mongodb_db, is_mongodb_backend
    from pallas.core.foundation.db.modules import Context, Message

    if not is_mongodb_backend():
        return CorpusCleanupReport(0, 0, 0, 0, 0, 0)

    await init_mongodb_db()
    include_message_history = (
        corpus_cleanup_message_history_enabled() if clean_message_history is None else bool(clean_message_history)
    )

    coll = Context.get_pymongo_collection()
    pending_updates: list[tuple[Any, list[dict[str, Any]]]] = []
    removed_message_candidates = 0
    removed_answer_candidates = 0
    preview_shown = 0

    async for doc in coll.find({}):
        answers = list(doc.get("answers") or [])
        if not answers:
            continue
        new_answers, removed_messages, removed_answers = prune_polluted_context_answers(answers)
        if removed_messages <= 0 and removed_answers <= 0:
            continue
        removed_message_candidates += removed_messages
        removed_answer_candidates += removed_answers
        if preview_limit > 0 and preview_shown < preview_limit:
            for answer in answers:
                for message in answer.get("messages") or []:
                    hit = match_corpus_learn_block(str(message))
                    if hit is None:
                        continue
                    logger.info(
                        "[corpus-cleanup] context={} group={} msg={}",
                        str(doc.get("keywords") or "")[:24],
                        answer.get("group_id"),
                        str(message)[:90],
                    )
                    preview_shown += 1
                    if preview_shown >= preview_limit:
                        break
                if preview_shown >= preview_limit:
                    break
        pending_updates.append((doc["_id"], new_answers))

    message_query = build_mongo_substr_query(
        "plain_text",
        CORPUS_LEARN_BLOCK_PHRASES,
        CORPUS_LEARN_EXCLUDE_SUBSTR,
    )
    message_candidates = 0
    if include_message_history and message_query:
        message_candidates = await Message.find(message_query).count()

    if preview_limit > 0 and include_message_history and message_query:
        preview_messages = await Message.find(message_query).limit(min(preview_limit, 10)).to_list()
        for row in preview_messages:
            logger.info(
                "[corpus-cleanup] message bot={} group={} text={}",
                row.bot_id,
                row.group_id,
                str(row.plain_text)[:120],
            )

    report = CorpusCleanupReport(
        answer_message_candidates=removed_message_candidates,
        parent_answer_candidates=removed_answer_candidates,
        message_candidates=message_candidates,
        deleted_answer_messages=0,
        deleted_empty_answers=0,
        deleted_message_history=0,
    )
    if not apply or (not pending_updates and message_candidates <= 0):
        return report

    deleted_messages = 0
    deleted_answers = 0
    deleted_history = 0

    for doc_id, new_answers in pending_updates:
        await coll.update_one({"_id": doc_id}, {"$set": {"answers": new_answers}})

    deleted_messages = removed_message_candidates
    deleted_answers = removed_answer_candidates

    if include_message_history and message_query:
        delete_result = await Message.find(message_query).delete()
        if delete_result is not None:
            deleted_history = int(getattr(delete_result, "deleted_count", 0) or 0)

    try:
        from pallas.product.corpus.find_cache import invalidate_find_cache

        await invalidate_find_cache(None)
    except Exception:
        pass

    logger.info(
        "corpus cleanup mongo apply={} deleted answer_messages={} empty_answers={} message_history={}",
        apply,
        deleted_messages,
        deleted_answers,
        deleted_history,
    )
    return CorpusCleanupReport(
        answer_message_candidates=removed_message_candidates,
        parent_answer_candidates=removed_answer_candidates,
        message_candidates=message_candidates,
        deleted_answer_messages=deleted_messages,
        deleted_empty_answers=deleted_answers,
        deleted_message_history=deleted_history,
    )


async def run_pg_corpus_contamination_cleanup(
    *,
    apply: bool,
    preview_limit: int = 20,
    clean_message_history: bool | None = None,
) -> CorpusCleanupReport:
    from pallas.core.foundation.db import init_postgresql_db, is_postgresql_backend
    from pallas.core.foundation.db.repository_pg import clear_reply_query_snapshot_cache, get_session

    if not is_postgresql_backend():
        return CorpusCleanupReport(0, 0, 0, 0, 0, 0)

    await init_postgresql_db()
    include_message_history = (
        corpus_cleanup_message_history_enabled() if clean_message_history is None else bool(clean_message_history)
    )

    like_clause, like_params = build_like_clause("cam.message", CORPUS_LEARN_BLOCK_PHRASES, prefix="p")
    exclude_clause, exclude_params = build_like_clause("cam.message", CORPUS_LEARN_EXCLUDE_SUBSTR, prefix="x")
    exclude_sql = f" AND NOT ({exclude_clause})" if exclude_clause else ""

    select_answer_sql = text(
        f"""
        SELECT cam.id, cam.answer_id, cam.message, ca.group_id, c.keywords
        FROM context_answer_message cam
        JOIN context_answer ca ON ca.id = cam.answer_id
        JOIN context c ON c.id = ca.context_id
        WHERE ({like_clause}){exclude_sql}
        ORDER BY cam.id
        """
    ).bindparams(*[bindparam(key) for key in like_params], *[bindparam(key) for key in exclude_params])

    msg_like_clause, msg_like_params = build_like_clause("plain_text", CORPUS_LEARN_BLOCK_PHRASES, prefix="m")
    msg_exclude_clause, msg_exclude_params = build_like_clause("plain_text", CORPUS_LEARN_EXCLUDE_SUBSTR, prefix="mx")
    msg_exclude_sql = f" AND NOT ({msg_exclude_clause})" if msg_exclude_clause else ""
    select_message_sql = text(
        f"""
        SELECT id, bot_id, group_id, left(plain_text, 120) AS preview
        FROM message
        WHERE ({msg_like_clause}){msg_exclude_sql}
        ORDER BY id
        """
    ).bindparams(*[bindparam(key) for key in msg_like_params], *[bindparam(key) for key in msg_exclude_params])

    async with get_session(read_only=True) as session:
        answer_rows = (await session.execute(select_answer_sql, {**like_params, **exclude_params})).all()
        message_rows = []
        if include_message_history:
            message_rows = (await session.execute(select_message_sql, {**msg_like_params, **msg_exclude_params})).all()

    answer_ids = sorted({int(row[0]) for row in answer_rows})
    parent_answer_ids = sorted({int(row[1]) for row in answer_rows})

    if preview_limit > 0:
        for row in answer_rows[:preview_limit]:
            logger.info(
                "[corpus-cleanup] answer id={} group={} ctx={} msg={}",
                row[0],
                row[3],
                str(row[4])[:24],
                str(row[2])[:90],
            )
        for row in message_rows[: min(preview_limit, 10)]:
            logger.info(
                "[corpus-cleanup] message id={} bot={} group={} text={}",
                row[0],
                row[1],
                row[2],
                row[3],
            )

    report = CorpusCleanupReport(
        answer_message_candidates=len(answer_ids),
        parent_answer_candidates=len(parent_answer_ids),
        message_candidates=len(message_rows),
        deleted_answer_messages=0,
        deleted_empty_answers=0,
        deleted_message_history=0,
    )
    if not apply or (not answer_ids and not message_rows):
        return report

    deleted_messages = 0
    deleted_answers = 0
    deleted_history = 0

    async with get_session() as session:
        if answer_ids:
            for offset in range(0, len(answer_ids), 500):
                chunk = answer_ids[offset : offset + 500]
                result = await session.execute(
                    text("DELETE FROM context_answer_message WHERE id IN :ids").bindparams(
                        bindparam("ids", expanding=True)
                    ),
                    {"ids": chunk},
                )
                deleted_messages += int(result.rowcount or 0)

            orphan_result = await session.execute(
                text(
                    """
                    DELETE FROM context_answer ca
                    WHERE NOT EXISTS (
                        SELECT 1 FROM context_answer_message cam WHERE cam.answer_id = ca.id
                    )
                    """
                )
            )
            deleted_answers = int(orphan_result.rowcount or 0)

        if message_rows:
            msg_ids = [int(row[0]) for row in message_rows]
            for offset in range(0, len(msg_ids), 500):
                chunk = msg_ids[offset : offset + 500]
                result = await session.execute(
                    text("DELETE FROM message WHERE id IN :ids").bindparams(bindparam("ids", expanding=True)),
                    {"ids": chunk},
                )
                deleted_history += int(result.rowcount or 0)

        await session.commit()

    try:
        await clear_reply_query_snapshot_cache(None)
    except Exception:
        pass

    logger.info(
        "corpus cleanup apply={} deleted answer_messages={} empty_answers={} message_history={}",
        apply,
        deleted_messages,
        deleted_answers,
        deleted_history,
    )
    return CorpusCleanupReport(
        answer_message_candidates=len(answer_ids),
        parent_answer_candidates=len(parent_answer_ids),
        message_candidates=len(message_rows),
        deleted_answer_messages=deleted_messages,
        deleted_empty_answers=deleted_answers,
        deleted_message_history=deleted_history,
    )
