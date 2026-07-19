"""多读源 ContextRepository：local + 可选 fed / community。"""

from __future__ import annotations

from typing import TYPE_CHECKING

from nonebot import logger

from pallas.core.platform.observability import SlowPathTimer, slow_path_threshold_ms
from pallas.product.corpus.config import (
    CorpusConfig,
    get_corpus_config,
    remote_corpus_find_enabled,
    remote_corpus_find_mode,
)
from pallas.product.corpus.merge import merge_contexts
from pallas.product.corpus.write_fanout import schedule_mirror_insert, schedule_mirror_upsert_answer

if TYPE_CHECKING:
    from pallas.core.foundation.db.modules import Answer, Ban, Context
    from pallas.core.foundation.db.repository import ContextRepository


class CompositeContextRepository:
    """多读源 merge；写路由 local + 可选异步 mirror。"""

    def __init__(
        self,
        local: ContextRepository,
        *,
        fed: ContextRepository | None = None,
        community: ContextRepository | None = None,
        cfg: CorpusConfig | None = None,
    ) -> None:
        self._local = local
        self._fed = fed
        self._community = community
        self._cfg = cfg or get_corpus_config()

    def _repo_for(self, source_id: str) -> ContextRepository | None:
        if source_id == "local":
            return self._local
        if source_id == "fed":
            return self._fed
        if source_id == "community":
            return self._community
        return None

    async def find_by_keywords(self, keywords: str) -> Context | None:
        from pallas.product.corpus.find_cache import cached_find_by_keywords

        return await cached_find_by_keywords(keywords, self._find_by_keywords_merged)

    async def find_by_keywords_for_reply(self, keywords: str) -> Context | None:
        """接话热路径：prefetch 仅本地查库并异步回填；sync 保持合并远程。"""
        from pallas.product.corpus.find_cache import cached_find_by_keywords_for_reply

        return await cached_find_by_keywords_for_reply(keywords, self._find_by_keywords_for_reply_uncached)

    async def _find_by_keywords_for_reply_uncached(self, keywords: str) -> Context | None:
        """接话热路径未缓存版本，供进程内 TTL 缓存包装。"""
        mode = remote_corpus_find_mode(self._cfg)
        if mode == "sync":
            return await self.find_by_keywords(keywords)
        ctx = await self._find_local_for_reply(keywords)
        if self.local_first_has_answers(ctx):
            return ctx
        if mode == "prefetch":
            from pallas.product.corpus.prefetch import schedule_corpus_prefetch

            schedule_corpus_prefetch(keywords)
        return None

    async def _find_local_for_reply(self, keywords: str) -> Context | None:
        find_reply = getattr(self._local, "find_by_keywords_for_reply", None)
        if callable(find_reply):
            return await find_reply(keywords)
        return await self._local.find_by_keywords(keywords)

    @staticmethod
    def local_first_has_answers(ctx: Context | None) -> bool:
        return ctx is not None and bool(ctx.answers)

    async def local_context_exists_by_keywords(self, keywords: str) -> bool:
        """学习路径专用：仅查本地库，不触发 fed/community。"""
        timer = SlowPathTimer(
            "corpus.local_context_exists",
            threshold_ms=slow_path_threshold_ms("PALLAS_SLOW_CORPUS_EXISTS_MS", 30.0),
        )
        exists = await self._local.context_exists_by_keywords(keywords)
        timer.mark("local_exists")
        timer.finish(keyword_len=len(keywords), hit=exists)
        return exists

    async def _find_by_keywords_merged(self, keywords: str) -> Context | None:
        timer = SlowPathTimer(
            "corpus.find_by_keywords",
            threshold_ms=slow_path_threshold_ms("PALLAS_SLOW_CORPUS_FIND_MS", 80.0),
        )
        merged: Context | None = None
        remote_find = remote_corpus_find_mode(self._cfg) == "sync"
        strategy = str(self._cfg.merge_strategy or "local_first")
        outcome = "merged"
        for source_id in self._cfg.merge_order:
            if not remote_find and source_id != "local":
                continue
            if source_id != "local":
                from pallas.product.corpus.remote_budget import should_skip_remote_corpus

                if should_skip_remote_corpus(hot_path=True):
                    continue
            repo = self._repo_for(source_id)
            if repo is None:
                continue
            try:
                find_reply = getattr(repo, "find_by_keywords_for_reply", None)
                if source_id == "local" and callable(find_reply):
                    ctx = await find_reply(keywords)
                else:
                    ctx = await repo.find_by_keywords(keywords)
                timer.mark(f"{source_id}_find")
            except Exception as e:
                outcome = f"{source_id}_error"
                if source_id != "local" and self._cfg.on_remote_failure == "local_only":
                    logger.warning(f"corpus {source_id} find_by_keywords failed: {e}")
                    continue
                timer.finish(
                    keyword_len=len(keywords),
                    remote_find=remote_find,
                    strategy=strategy,
                    outcome=outcome,
                )
                raise
            merged = merge_contexts(merged, ctx, strategy=strategy)
            if source_id == "local" and strategy == "local_first" and self.local_first_has_answers(merged):
                outcome = "local_short_circuit"
                timer.finish(
                    keyword_len=len(keywords),
                    remote_find=remote_find,
                    strategy=strategy,
                    outcome=outcome,
                )
                return merged
        timer.finish(
            keyword_len=len(keywords),
            remote_find=remote_find,
            strategy=strategy,
            outcome=outcome,
        )
        return merged

    async def context_exists_by_keywords(self, keywords: str) -> bool:
        if await self._local.context_exists_by_keywords(keywords):
            return True
        if not remote_corpus_find_enabled(self._cfg):
            return False
        from pallas.product.corpus.remote_budget import should_skip_remote_corpus

        if should_skip_remote_corpus(hot_path=True):
            return False
        for source_id in ("fed", "community"):
            repo = self._repo_for(source_id)
            if repo is None:
                continue
            try:
                if await repo.context_exists_by_keywords(keywords):
                    return True
            except Exception as e:
                if self._cfg.on_remote_failure == "local_only":
                    logger.warning(f"corpus {source_id} context_exists failed: {e}")
                    continue
                raise
        return False

    async def save(self, context: Context) -> None:
        await self._local.save(context)

    async def insert(self, context: Context) -> None:
        await self._local.insert(context)
        from pallas.product.corpus.find_cache import invalidate_find_cache

        await invalidate_find_cache(context.keywords)
        schedule_mirror_insert(fed=self._fed, community=self._community, cfg=self._cfg, context=context)

    async def delete_expired(self, expiration: int, threshold: int) -> None:
        await self._local.delete_expired(expiration, threshold)

    async def find_for_cleanup(self, trigger_threshold: int, expiration: int) -> list[Context]:
        return await self._local.find_for_cleanup(trigger_threshold, expiration)

    async def upsert_answer(
        self,
        keywords: str,
        group_id: int,
        answer_keywords: str,
        answer_time: int,
        message: str,
        append_on_existing: bool,
    ) -> None:
        from pallas.product.llm.corpus_contamination import reject_corpus_learn_message

        if reject_corpus_learn_message(message, source="composite_upsert_answer"):
            return
        await self._local.upsert_answer(
            keywords=keywords,
            group_id=group_id,
            answer_keywords=answer_keywords,
            answer_time=answer_time,
            message=message,
            append_on_existing=append_on_existing,
        )
        from pallas.product.corpus.find_cache import invalidate_find_cache

        await invalidate_find_cache(keywords)
        schedule_mirror_upsert_answer(
            fed=self._fed,
            community=self._community,
            cfg=self._cfg,
            keywords=keywords,
            group_id=group_id,
            answer_keywords=answer_keywords,
            answer_time=answer_time,
            message=message,
            append_on_existing=append_on_existing,
        )

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
        from pallas.product.llm.corpus_contamination import reject_corpus_learn_message

        if reject_corpus_learn_message(message, source="composite_learn_answer"):
            return False
        local_learn = getattr(self._local, "learn_answer", None)
        if callable(local_learn):
            created = bool(
                await local_learn(
                    keywords=keywords,
                    group_id=group_id,
                    answer_keywords=answer_keywords,
                    answer_time=answer_time,
                    message=message,
                    append_on_existing=append_on_existing,
                )
            )
        else:
            from pallas.core.foundation.db.modules import Answer, Context

            created = not await self._local.context_exists_by_keywords(keywords)
            if created:
                context = Context.model_construct(
                    keywords=keywords,
                    time=answer_time,
                    trigger_count=1,
                    answers=[
                        Answer(
                            keywords=answer_keywords,
                            group_id=group_id,
                            count=1,
                            time=answer_time,
                            messages=[message],
                        )
                    ],
                    ban=[],
                    clear_time=0,
                )
                await self._local.insert(context)
            else:
                await self._local.upsert_answer(
                    keywords=keywords,
                    group_id=group_id,
                    answer_keywords=answer_keywords,
                    answer_time=answer_time,
                    message=message,
                    append_on_existing=append_on_existing,
                )

        from pallas.core.foundation.db.modules import Answer, Context
        from pallas.product.corpus.find_cache import invalidate_find_cache

        await invalidate_find_cache(keywords)
        if created:
            schedule_mirror_insert(
                fed=self._fed,
                community=self._community,
                cfg=self._cfg,
                context=Context.model_construct(
                    keywords=keywords,
                    time=answer_time,
                    trigger_count=1,
                    answers=[
                        Answer(
                            keywords=answer_keywords,
                            group_id=group_id,
                            count=1,
                            time=answer_time,
                            messages=[message],
                        )
                    ],
                    ban=[],
                    clear_time=0,
                ),
            )
        else:
            schedule_mirror_upsert_answer(
                fed=self._fed,
                community=self._community,
                cfg=self._cfg,
                keywords=keywords,
                group_id=group_id,
                answer_keywords=answer_keywords,
                answer_time=answer_time,
                message=message,
                append_on_existing=append_on_existing,
            )
        return created

    async def replace_answers(self, keywords: str, answers: list[Answer], clear_time: int) -> None:
        await self._local.replace_answers(keywords, answers, clear_time)

    async def append_ban(self, keywords: str, ban: Ban) -> None:
        await self._local.append_ban(keywords, ban)

    async def find_ban_reply_target(self, group_id: int, reply_message: str) -> tuple[str, str] | None:
        find_target = getattr(self._local, "find_ban_reply_target", None)
        if not callable(find_target):
            return None
        return await find_target(group_id, reply_message)
