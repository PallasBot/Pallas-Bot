"""PostgreSQL Context Repository（语料）"""

from __future__ import annotations

import hashlib
import json
import time
from typing import TYPE_CHECKING

from nonebot import logger
from sqlalchemy import delete, func, insert, literal_column, or_, select, text, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import selectinload

from pallas.core.foundation.db import repository_pg as _repo
from pallas.core.foundation.db.repository_pg.lifecycle import (
    _s,
    cached_reply_query_snapshot,
    clear_reply_query_snapshot_cache,
)
from pallas.core.foundation.db.repository_pg.schema import (
    ContextAnswerMessageRow,
    ContextAnswerRow,
    ContextBanRow,
    ContextRow,
)
from pallas.core.platform.observability import slow_path_threshold_ms

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from pallas.core.foundation.db.modules import Answer, Ban, Context

_LOAD_RELATED = [
    selectinload(ContextRow.answers).selectinload(ContextAnswerRow.messages),
    selectinload(ContextRow.ban),
]

_LOAD_REPLY_CTX = [
    selectinload(ContextRow.ban),
]


def keywords_hash(keywords: str) -> str:
    # 先剥除 \x00 再哈希，与 ContextRow.keywords 实际存储值保持一致
    clean = keywords.replace("\x00", "") if keywords and "\x00" in keywords else keywords
    return hashlib.md5((clean or "").encode("utf-8", errors="replace")).hexdigest()


# asyncpg 单语句参数上限 32767
_ANSWER_BATCH = 500  # ContextAnswerRow 6 列 × 500 = 3000
_MSG_BATCH = 16000  # ContextAnswerMessageRow 2 列 × 16000 = 32000
_DELETE_ID_BATCH = 1000


async def delete_context_answer_orphans(
    session: AsyncSession,
    *,
    ctx_id: int,
    kept_ids: list[int],
    chunk_size: int = _DELETE_ID_BATCH,
) -> None:
    """删除指定 Context 下未保留的 Answer，避免生成超长 NOT IN 参数列表。"""
    if not kept_ids:
        await session.execute(delete(ContextAnswerRow).where(ContextAnswerRow.context_id == ctx_id))
        return

    existing_ids = (
        (await session.execute(select(ContextAnswerRow.id).where(ContextAnswerRow.context_id == ctx_id)))
        .scalars()
        .all()
    )
    kept_id_set = set(kept_ids)
    orphan_ids = [int(ans_id) for ans_id in existing_ids if int(ans_id) not in kept_id_set]
    for offset in range(0, len(orphan_ids), chunk_size):
        chunk = orphan_ids[offset : offset + chunk_size]
        await session.execute(
            delete(ContextAnswerRow).where(ContextAnswerRow.context_id == ctx_id, ContextAnswerRow.id.in_(chunk))
        )


_BAN_BATCH = 6000  # ContextBanRow 5 列 × 6000 = 30000


async def _insert_answers_batched(session: AsyncSession, context_id: int, answers) -> None:
    """分批插入 ContextAnswerRow 及其关联的 ContextAnswerMessageRow"""

    for i in range(0, len(answers), _ANSWER_BATCH):
        batch: list[Answer] = answers[i : i + _ANSWER_BATCH]
        rows = []
        for a in batch:
            kw = _s(a.keywords) or ""
            rows.append(
                ContextAnswerRow(
                    context_id=context_id,
                    keywords=kw,
                    keywords_hash=keywords_hash(kw),
                    group_id=a.group_id,
                    count=a.count,
                    time=a.time,
                )
            )
        session.add_all(rows)
        await session.flush()

        msg_rows = [
            ContextAnswerMessageRow(answer_id=rows[j].id, message=_s(m) or "")
            for j, a in enumerate(batch)
            for m in a.messages
        ]
        for k in range(0, len(msg_rows), _MSG_BATCH):
            session.add_all(msg_rows[k : k + _MSG_BATCH])
            await session.flush()


async def _insert_bans_batched(session: AsyncSession, context_id: int, bans) -> None:
    """分批插入 ContextBanRow"""
    for i in range(0, len(bans), _BAN_BATCH):
        batch = bans[i : i + _BAN_BATCH]
        session.add_all([
            ContextBanRow(
                context_id=context_id,
                keywords=_s(b.keywords) or "",
                group_id=b.group_id,
                reason=_s(b.reason) or "",
                time=b.time,
            )
            for b in batch
        ])
        await session.flush()


def row_to_context(row: ContextRow, *, reply_messages: dict[int, list[str]] | None = None) -> Context:
    from pallas.core.foundation.db.modules import Answer, Ban, Context

    answers = []
    for a in row.answers:
        if reply_messages is not None:
            msgs = list(reply_messages.get(int(a.id), []))
        else:
            msgs = [m.message for m in a.messages]
        answers.append(
            Answer.model_construct(
                keywords=a.keywords,
                group_id=a.group_id,
                count=a.count,
                time=a.time,
                messages=msgs,
            )
        )
    ban = [
        Ban.model_construct(
            keywords=b.keywords,
            group_id=b.group_id,
            reason=b.reason,
            time=b.time,
        )
        for b in row.ban
    ]
    return Context.model_construct(
        keywords=row.keywords,
        time=row.time,
        trigger_count=row.trigger_count,
        answers=answers,
        ban=ban,
        clear_time=row.clear_time,
    )


def build_reply_context(
    *,
    keywords: str,
    time_value: int,
    trigger_count: int,
    clear_time: int,
    answer_rows: list[ContextAnswerRow],
    ban_rows: list[ContextBanRow],
    reply_messages: dict[int, list[str]],
):
    from pallas.core.foundation.db.modules import Answer, Ban, Context

    return Context.model_construct(
        keywords=keywords,
        time=time_value,
        trigger_count=trigger_count,
        answers=[
            Answer.model_construct(
                keywords=answer.keywords,
                group_id=answer.group_id,
                count=answer.count,
                time=answer.time,
                messages=list(reply_messages.get(int(answer.id), [])),
            )
            for answer in answer_rows
        ],
        ban=[
            Ban.model_construct(
                keywords=ban.keywords,
                group_id=ban.group_id,
                reason=ban.reason,
                time=ban.time,
            )
            for ban in ban_rows
        ],
        clear_time=clear_time,
    )


def build_reply_message_query(answer_ids: list[int], msg_cap: int):
    rn = (
        func
        .row_number()
        .over(
            partition_by=ContextAnswerMessageRow.answer_id,
            order_by=ContextAnswerMessageRow.id.desc(),
        )
        .label("rn")
    )
    ranked = (
        select(
            ContextAnswerMessageRow.answer_id,
            ContextAnswerMessageRow.message,
            ContextAnswerMessageRow.id,
            rn,
        )
        .where(ContextAnswerMessageRow.answer_id.in_(answer_ids))
        .subquery()
    )
    return (
        select(ranked.c.answer_id, ranked.c.message, ranked.c.id)
        .where(ranked.c.rn <= msg_cap)
        .order_by(ranked.c.answer_id, ranked.c.id)
    )


class PgContextRepository:
    async def context_exists_by_keywords(self, keywords: str) -> bool:
        khash = keywords_hash(keywords)
        async with _repo.get_session(read_only=True) as session:
            result = await session.execute(select(ContextRow.id).where(ContextRow.keywords_hash == khash).limit(1))
            return result.scalar_one_or_none() is not None

    async def find_by_keywords(self, keywords: str) -> Context | None:
        khash = keywords_hash(keywords)
        async with _repo.get_session(read_only=True) as session:
            result = await session.execute(
                select(ContextRow).options(*_LOAD_RELATED).where(ContextRow.keywords_hash == khash)
            )
            row = result.scalar_one_or_none()
            return row_to_context(row) if row else None

    async def find_by_keywords_for_reply(self, keywords: str) -> Context | None:
        return await cached_reply_query_snapshot(keywords, self._find_by_keywords_for_reply_uncached)

    async def _find_by_keywords_for_reply_uncached(self, keywords: str) -> Context | None:
        """接话路径：轻量列查询 + 限量 Answer/Message，避免 ORM 关联热路径放大。"""
        return await self._find_by_keywords_for_reply_snapshot(keywords)

    async def _find_by_keywords_for_reply_snapshot(self, keywords: str) -> Context | None:
        """一次受限快照读取接话所需的 context、ban、answer 与 message。"""
        from pallas.core.foundation.db.modules import Answer, Ban, Context

        khash = keywords_hash(keywords)
        from pallas.product.corpus.reply_perf_config import reply_query_caps

        msg_cap, ans_cap = reply_query_caps(keywords)
        t_start = time.monotonic()
        async with _repo.get_session(read_only=True) as session:
            context_row = (
                (
                    await session.execute(
                        text(
                            """
                        SELECT c.id, c.keywords, c.time, c.trigger_count, c.clear_time,
                            COALESCE((
                                SELECT jsonb_agg(jsonb_build_object(
                                    'keywords', b.keywords, 'group_id', b.group_id,
                                    'reason', b.reason, 'time', b.time
                                ) ORDER BY b.id)
                                FROM context_ban b WHERE b.context_id = c.id
                            ), '[]'::jsonb) AS bans
                        FROM context c WHERE c.keywords_hash = :khash
                        """
                        ),
                        {"khash": khash},
                    )
                )
                .mappings()
                .one_or_none()
            )
            row = None
            if context_row is not None:
                answer_row = (
                    (
                        await session.execute(
                            text(
                                """
                            WITH answers AS (
                                SELECT a.id, a.keywords, a.group_id, a.count, a.time
                                FROM context_answer a
                                WHERE a.context_id = :context_id
                                ORDER BY a.count DESC, a.time DESC LIMIT :ans_cap
                            ), ranked_messages AS (
                                SELECT m.answer_id, m.message, m.id,
                                       row_number() OVER (PARTITION BY m.answer_id ORDER BY m.id DESC) AS rn
                                FROM context_answer_message m JOIN answers a ON a.id = m.answer_id
                            ), messages AS (
                                SELECT answer_id, jsonb_agg(message ORDER BY id) AS values
                                FROM ranked_messages WHERE rn <= :msg_cap GROUP BY answer_id
                            )
                            SELECT COALESCE(jsonb_agg(jsonb_build_object(
                                'keywords', a.keywords, 'group_id', a.group_id,
                                'count', a.count, 'time', a.time,
                                'messages', COALESCE(m.values, '[]'::jsonb)
                            ) ORDER BY a.count DESC, a.time DESC), '[]'::jsonb) AS answers
                            FROM answers a LEFT JOIN messages m ON m.answer_id = a.id
                            """
                            ),
                            {"context_id": context_row["id"], "ans_cap": ans_cap, "msg_cap": msg_cap},
                        )
                    )
                    .mappings()
                    .one()
                )
                row = {**context_row, "answers": answer_row["answers"]}
        elapsed_ms = (time.monotonic() - t_start) * 1000.0
        if row is None:
            self._log_reply_query_slow(
                keywords=keywords,
                elapsed_ms=elapsed_ms,
                context_ms=None,
                ban_ms=None,
                answer_ms=None,
                message_ms=None,
                ban_count=0,
                answer_count=0,
                message_count=0,
                hit=False,
            )
            return None
        bans = row["bans"] if isinstance(row["bans"], list) else json.loads(row["bans"])
        answers = row["answers"] if isinstance(row["answers"], list) else json.loads(row["answers"])
        self._log_reply_query_slow(
            keywords=keywords,
            elapsed_ms=elapsed_ms,
            context_ms=None,
            ban_ms=None,
            answer_ms=None,
            message_ms=None,
            ban_count=len(bans),
            answer_count=len(answers),
            message_count=sum(len(answer["messages"]) for answer in answers),
            hit=True,
        )
        return Context.model_construct(
            keywords=row["keywords"],
            time=row["time"],
            trigger_count=row["trigger_count"],
            clear_time=row["clear_time"],
            ban=[Ban.model_construct(**ban) for ban in bans],
            answers=[Answer.model_construct(**answer) for answer in answers],
        )

    @staticmethod
    def _log_reply_query_slow(
        *,
        keywords: str,
        elapsed_ms: float,
        context_ms: float | None,
        ban_ms: float | None,
        answer_ms: float | None,
        message_ms: float | None,
        ban_count: int,
        answer_count: int,
        message_count: int,
        hit: bool,
    ) -> None:
        from pallas.core.platform.ingress.hotpath_metrics import record_reply_query_stages

        record_reply_query_stages(
            context_ms=context_ms,
            ban_ms=ban_ms,
            answer_ms=answer_ms,
            message_ms=message_ms,
            total_ms=elapsed_ms,
        )
        threshold_ms = slow_path_threshold_ms("PALLAS_SLOW_REPLY_QUERY_MS", 250.0)
        if elapsed_ms < threshold_ms:
            return
        logger.debug(
            "Corpus reply query used the slow path in [{:.1f}]ms: context [{:.1f}]ms, ban [{:.1f}]ms, "
            "answers [{:.1f}]ms, messages [{:.1f}]ms; counts were ban [{}], answers [{}], "
            "messages [{}], hit [{}], and keyword length [{}].",
            elapsed_ms,
            context_ms or 0.0,
            ban_ms or 0.0,
            answer_ms or 0.0,
            message_ms or 0.0,
            ban_count,
            answer_count,
            message_count,
            hit,
            len(keywords),
        )

    async def save(self, context: Context) -> None:
        khash = keywords_hash(context.keywords)
        async with _repo.get_session() as session:
            result = await session.execute(select(ContextRow).where(ContextRow.keywords_hash == khash))
            row = result.scalar_one_or_none()

            if row is None:
                row = ContextRow(
                    keywords=_s(context.keywords) or "",
                    keywords_hash=khash,
                    time=context.time,
                    trigger_count=context.trigger_count,
                    clear_time=context.clear_time,
                )
                session.add(row)
                await session.flush()
            else:
                row.time = context.time
                row.trigger_count = context.trigger_count
                row.clear_time = context.clear_time
                await session.execute(delete(ContextAnswerRow).where(ContextAnswerRow.context_id == row.id))
                await session.execute(delete(ContextBanRow).where(ContextBanRow.context_id == row.id))

            await _insert_answers_batched(session, row.id, context.answers)
            await _insert_bans_batched(session, row.id, context.ban)
            await session.commit()
        await clear_reply_query_snapshot_cache(context.keywords)

    async def insert(self, context: Context) -> None:
        """插入新 Context。并发下同 keywords 第二个写入会被 unique 约束拒绝，等价为 no-op。"""
        khash = keywords_hash(context.keywords)
        try:
            async with _repo.get_session() as session:
                row = ContextRow(
                    keywords=_s(context.keywords) or "",
                    keywords_hash=khash,
                    time=context.time,
                    trigger_count=context.trigger_count,
                    clear_time=context.clear_time,
                )
                session.add(row)
                await session.flush()
                await _insert_answers_batched(session, row.id, context.answers)
                await _insert_bans_batched(session, row.id, context.ban)
                await session.commit()
            await clear_reply_query_snapshot_cache(context.keywords)
        except IntegrityError:
            pass

    _DELETE_EXPIRED_CHUNK = 10000

    async def delete_expired(self, expiration: int, threshold: int) -> None:
        """分批删除过期 Context，避免千万级时长锁表。级联删除由 FK ondelete=CASCADE 处理。"""
        deleted_any = False
        while True:
            async with _repo.get_session() as session:
                subq = (
                    select(ContextRow.id)
                    .where(ContextRow.time < expiration, ContextRow.trigger_count < threshold)
                    .limit(self._DELETE_EXPIRED_CHUNK)
                    .subquery()
                )
                result = await session.execute(
                    delete(ContextRow).where(ContextRow.id.in_(select(subq.c.id))).returning(ContextRow.id)
                )
                deleted = len(result.scalars().all())
                await session.commit()
            deleted_any = deleted_any or deleted > 0
            if deleted < self._DELETE_EXPIRED_CHUNK:
                break
        if deleted_any:
            await clear_reply_query_snapshot_cache(None)

    _CLEANUP_CHUNK = 500

    async def find_for_cleanup(self, trigger_threshold: int, expiration: int) -> list[Context]:
        """
        语义对齐 Mongo：trigger_count > threshold OR clear_time < expiration。
        流式按主键 id 分页，避免千万级时一次性全加载 OOM。
        """
        results: list[Context] = []
        last_id = 0
        while True:
            async with _repo.get_session(read_only=True) as session:
                result = await session.execute(
                    select(ContextRow)
                    .options(*_LOAD_RELATED)
                    .where(
                        or_(
                            ContextRow.trigger_count > trigger_threshold,
                            ContextRow.clear_time < expiration,
                        ),
                        ContextRow.id > last_id,
                    )
                    .order_by(ContextRow.id)
                    .limit(self._CLEANUP_CHUNK)
                )
                rows = list(result.scalars().all())
            if not rows:
                break
            results.extend(row_to_context(r) for r in rows)
            last_id = rows[-1].id
            if len(rows) < self._CLEANUP_CHUNK:
                break
        return results

    async def upsert_answer(
        self,
        keywords: str,
        group_id: int,
        answer_keywords: str,
        answer_time: int,
        message: str,
        append_on_existing: bool,
    ) -> None:
        """
        原子 upsert，依赖 UNIQUE(context_id, group_id, keywords)：
          - INSERT ... ON CONFLICT DO UPDATE SET count = count + 1, time = EXCLUDED.time
          - RETURNING 中借助 xmax 判断 insert vs update，决定是否 append message
          - 最后原子递增 Context.trigger_count / 更新 time
        """
        khash = keywords_hash(keywords)
        ans_kw_s = _s(answer_keywords) or ""
        msg_s = _s(message) or ""
        from pallas.product.llm.corpus_contamination import reject_corpus_learn_message

        if reject_corpus_learn_message(msg_s, source="upsert_answer"):
            return

        async with _repo.get_session() as session:
            ctx_result = await session.execute(select(ContextRow.id).where(ContextRow.keywords_hash == khash))
            ctx_id = ctx_result.scalar_one_or_none()
            if ctx_id is None:
                return

            stmt = pg_insert(ContextAnswerRow).values(
                context_id=ctx_id,
                keywords=ans_kw_s,
                keywords_hash=keywords_hash(ans_kw_s),
                group_id=group_id,
                count=1,
                time=answer_time,
            )
            stmt = stmt.on_conflict_do_update(
                constraint="uq_context_answer_ctx_group_kw",
                set_={
                    "count": ContextAnswerRow.count + 1,
                    "time": stmt.excluded.time,
                },
            ).returning(ContextAnswerRow.id, literal_column("(xmax = 0)").label("was_insert"))

            row = (await session.execute(stmt)).first()
            assert row is not None
            ans_id, was_insert = int(row.id), bool(row.was_insert)

            if was_insert or append_on_existing:
                await session.execute(insert(ContextAnswerMessageRow).values(answer_id=ans_id, message=msg_s))

            await session.execute(
                update(ContextRow)
                .where(ContextRow.id == ctx_id)
                .values(trigger_count=ContextRow.trigger_count + 1, time=answer_time)
            )
            await session.commit()

    async def learn_answer(
        self,
        *,
        keywords: str,
        group_id: int,
        answer_keywords: str,
        answer_time: int,
        message: str,
        append_on_existing: bool,
    ) -> bool:
        """
        学习热路径专用：
          - Context 不存在时直接原子创建并写入首条 Answer
          - Context 已存在时在同一事务内原子 upsert Answer
        返回值表示本次是否新建了 Context。
        """
        khash = keywords_hash(keywords)
        kw_s = _s(keywords) or ""
        ans_kw_s = _s(answer_keywords) or ""
        msg_s = _s(message) or ""
        from pallas.product.llm.corpus_contamination import reject_corpus_learn_message

        if reject_corpus_learn_message(msg_s, source="learn_answer"):
            return False

        async with _repo.get_session() as session:
            ctx_stmt = pg_insert(ContextRow).values(
                keywords=kw_s,
                keywords_hash=khash,
                time=answer_time,
                trigger_count=1,
                clear_time=0,
            )
            ctx_stmt = ctx_stmt.on_conflict_do_update(
                index_elements=[ContextRow.keywords_hash],
                set_={
                    "trigger_count": ContextRow.trigger_count + 1,
                    "time": ctx_stmt.excluded.time,
                },
            ).returning(ContextRow.id, literal_column("(xmax = 0)").label("was_insert"))

            ctx_row = (await session.execute(ctx_stmt)).first()
            assert ctx_row is not None
            ctx_id, ctx_created = int(ctx_row.id), bool(ctx_row.was_insert)

            ans_stmt = pg_insert(ContextAnswerRow).values(
                context_id=ctx_id,
                keywords=ans_kw_s,
                keywords_hash=keywords_hash(ans_kw_s),
                group_id=group_id,
                count=1,
                time=answer_time,
            )
            ans_stmt = ans_stmt.on_conflict_do_update(
                constraint="uq_context_answer_ctx_group_kw",
                set_={
                    "count": ContextAnswerRow.count + 1,
                    "time": ans_stmt.excluded.time,
                },
            ).returning(ContextAnswerRow.id, literal_column("(xmax = 0)").label("was_insert"))

            ans_row = (await session.execute(ans_stmt)).first()
            assert ans_row is not None
            ans_id, answer_created = int(ans_row.id), bool(ans_row.was_insert)

            if answer_created or append_on_existing:
                await session.execute(insert(ContextAnswerMessageRow).values(answer_id=ans_id, message=msg_s))

            await session.commit()
            if ctx_created:
                await clear_reply_query_snapshot_cache(keywords)
            return ctx_created

    async def replace_answers(self, keywords: str, answers: list[Answer], clear_time: int) -> None:
        khash = keywords_hash(keywords)
        async with _repo.get_session() as session:
            ctx_result = await session.execute(select(ContextRow).where(ContextRow.keywords_hash == khash))
            ctx_row = ctx_result.scalar_one_or_none()
            if ctx_row is None:
                return

            ctx_id = int(ctx_row.id)
            await session.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": ctx_id})

            kept_ids: list[int] = []
            for answer in answers:
                kw = _s(answer.keywords) or ""
                ans_stmt = (
                    pg_insert(ContextAnswerRow)
                    .values(
                        context_id=ctx_id,
                        keywords=kw,
                        keywords_hash=keywords_hash(kw),
                        group_id=answer.group_id,
                        count=answer.count,
                        time=answer.time,
                    )
                    .on_conflict_do_update(
                        constraint="uq_context_answer_ctx_group_kw",
                        set_={
                            "keywords": kw,
                            "count": answer.count,
                            "time": answer.time,
                        },
                    )
                    .returning(ContextAnswerRow.id)
                )
                ans_id = int((await session.execute(ans_stmt)).scalar_one())
                kept_ids.append(ans_id)

                await session.execute(
                    delete(ContextAnswerMessageRow).where(ContextAnswerMessageRow.answer_id == ans_id)
                )
                msg_rows = [
                    ContextAnswerMessageRow(answer_id=ans_id, message=_s(message) or "") for message in answer.messages
                ]
                for offset in range(0, len(msg_rows), _MSG_BATCH):
                    session.add_all(msg_rows[offset : offset + _MSG_BATCH])
                    await session.flush()

            await delete_context_answer_orphans(session, ctx_id=ctx_id, kept_ids=kept_ids)

            ctx_row.clear_time = clear_time
            await session.commit()
        await clear_reply_query_snapshot_cache(keywords)

    async def append_ban(self, keywords: str, ban: Ban) -> None:
        khash = keywords_hash(keywords)
        async with _repo.get_session() as session:
            ctx_result = await session.execute(select(ContextRow.id).where(ContextRow.keywords_hash == khash))
            ctx_id = ctx_result.scalar_one_or_none()
            if ctx_id is None:
                return

            await session.execute(
                insert(ContextBanRow).values(
                    context_id=ctx_id,
                    keywords=_s(ban.keywords) or "",
                    group_id=ban.group_id,
                    reason=_s(ban.reason) or "",
                    time=ban.time,
                )
            )
            await session.commit()
        await clear_reply_query_snapshot_cache(keywords)

    async def find_ban_reply_target(self, group_id: int, reply_message: str) -> tuple[str, str] | None:
        async with _repo.get_session(read_only=True) as session:
            result = await session.execute(
                select(ContextRow.keywords, ContextAnswerRow.keywords)
                .join(ContextAnswerRow, ContextAnswerRow.context_id == ContextRow.id)
                .join(ContextAnswerMessageRow, ContextAnswerMessageRow.answer_id == ContextAnswerRow.id)
                .where(
                    ContextAnswerRow.group_id == int(group_id),
                    ContextAnswerMessageRow.message == _s(reply_message),
                )
                .order_by(ContextAnswerRow.time.desc(), ContextAnswerMessageRow.id.desc())
                .limit(1)
            )
            row = result.one_or_none()
            if row is None:
                return None
            pre_keywords, reply_keywords = row
            return str(pre_keywords), str(reply_keywords)

    async def list_answers_for_group_since(self, group_id: int, cutoff_time: int) -> list[Answer]:
        from pallas.core.foundation.db.modules import Answer

        async with _repo.get_session(read_only=True) as session:
            result = await session.execute(
                select(ContextAnswerRow)
                .where(
                    ContextAnswerRow.group_id == int(group_id),
                    ContextAnswerRow.time >= int(cutoff_time),
                )
                .options(selectinload(ContextAnswerRow.messages))
            )
            rows = list(result.scalars().all())
        return [
            Answer(
                keywords=str(row.keywords),
                group_id=int(row.group_id),
                count=int(row.count),
                time=int(row.time),
                messages=[str(msg.message) for msg in row.messages],
            )
            for row in rows
        ]
