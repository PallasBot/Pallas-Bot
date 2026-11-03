"""
PostgreSQL Repository 集成测试。

依赖：本地 PG 实例。fixture 定义在 ``conftest.py``，
未设置 DSN 时整套用例自动 skip。

覆盖矩阵：
- Context：``find_for_cleanup`` OR 语义 / ``upsert_answer`` 并发原子与 append 标志
  / 缺上下文 no-op / ``delete_expired`` 分块
- \\x00 过滤：Context + Message 全链路
- BlackList / ImageCache：upsert 原子性 / save() 语义
- ConfigRepository：TTL 缓存命中、写失效、ignore_cache 回源、全量失效、并发
  get_or_create
"""

from __future__ import annotations

import asyncio
import uuid

import pytest
from sqlalchemy.dialects import postgresql


@pytest.mark.asyncio
async def test_find_for_cleanup_or_semantics(pg_engine):
    """trigger_count>threshold 与 clear_time<expiration 必须是 OR 关系。"""
    from pallas.core.foundation.db.modules import Context
    from pallas.core.foundation.db.repository_pg import PgContextRepository

    repo = PgContextRepository()
    await repo.insert(
        Context.model_construct(keywords="high", time=1000, trigger_count=150, answers=[], ban=[], clear_time=999)
    )
    await repo.insert(
        Context.model_construct(keywords="old", time=1000, trigger_count=5, answers=[], ban=[], clear_time=100)
    )
    await repo.insert(
        Context.model_construct(keywords="neither", time=1000, trigger_count=5, answers=[], ban=[], clear_time=999)
    )

    results = await repo.find_for_cleanup(trigger_threshold=100, expiration=500)
    got = {c.keywords for c in results}
    assert "high" in got
    assert "old" in got
    assert "neither" not in got


@pytest.mark.asyncio
async def test_context_exists_by_keywords(pg_engine):
    """Learner仅需分支判断时应只查 id，避免误用全量 find_by_keywords。"""
    from pallas.core.foundation.db.modules import Context
    from pallas.core.foundation.db.repository_pg import PgContextRepository

    repo = PgContextRepository()
    assert await repo.context_exists_by_keywords("absent_kw") is False
    await repo.insert(
        Context.model_construct(keywords="present_kw", time=0, trigger_count=1, answers=[], ban=[], clear_time=0)
    )
    assert await repo.context_exists_by_keywords("present_kw") is True


@pytest.mark.asyncio
async def test_upsert_answer_is_atomic(pg_engine):
    """并发 50 次 upsert_answer 只产生 1 条 Answer、count=50、trigger_count 精确累加。"""
    from pallas.core.foundation.db.modules import Context
    from pallas.core.foundation.db.repository_pg import PgContextRepository

    repo = PgContextRepository()
    await repo.insert(Context.model_construct(keywords="kw", time=0, trigger_count=1, answers=[], ban=[], clear_time=0))

    async def _u(i: int):
        await repo.upsert_answer(
            keywords="kw",
            group_id=1,
            answer_keywords="a",
            answer_time=100 + i,
            message=f"m{i}",
            append_on_existing=True,
        )

    await asyncio.gather(*[_u(i) for i in range(50)])

    found = await repo.find_by_keywords("kw")
    assert found is not None
    assert len(found.answers) == 1
    assert found.answers[0].count == 50
    assert len(found.answers[0].messages) == 50
    assert found.trigger_count == 1 + 50


@pytest.mark.asyncio
async def test_replace_answers_upserts_and_drops_orphans(pg_engine):
    from pallas.core.foundation.db.modules import Answer, Context
    from pallas.core.foundation.db.repository_pg import PgContextRepository

    repo = PgContextRepository()
    await repo.insert(
        Context.model_construct(
            keywords="kw-replace",
            time=0,
            trigger_count=1,
            answers=[
                Answer.model_construct(
                    keywords="old-a",
                    group_id=1,
                    count=2,
                    time=10,
                    messages=["m-old"],
                ),
                Answer.model_construct(
                    keywords="drop-me",
                    group_id=2,
                    count=1,
                    time=11,
                    messages=["gone"],
                ),
            ],
            ban=[],
            clear_time=0,
        )
    )

    await repo.replace_answers(
        "kw-replace",
        [
            Answer.model_construct(
                keywords="old-a",
                group_id=1,
                count=5,
                time=99,
                messages=["m-new-1", "m-new-2"],
            ),
            Answer.model_construct(
                keywords="new-b",
                group_id=3,
                count=1,
                time=100,
                messages=["fresh"],
            ),
        ],
        clear_time=123,
    )

    found = await repo.find_by_keywords("kw-replace")
    assert found is not None
    assert found.clear_time == 123
    assert len(found.answers) == 2
    by_kw = {ans.keywords: ans for ans in found.answers}
    assert by_kw["old-a"].count == 5
    assert by_kw["old-a"].messages == ["m-new-1", "m-new-2"]
    assert by_kw["new-b"].group_id == 3
    assert "drop-me" not in by_kw


@pytest.mark.asyncio
async def test_find_by_keywords_for_reply_caps_messages(pg_engine, monkeypatch):
    """接话 find 仅加载最近 N 条 message，全量 find 不受影响。"""
    from pallas.core.foundation.db import repository_pg as pg_mod
    from pallas.core.foundation.db.modules import Context
    from pallas.product.corpus.reply_perf_config import clear_corpus_reply_perf_config_cache

    monkeypatch.setenv("PALLAS_CORPUS_REPLY_MESSAGES_CAP", "8")
    clear_corpus_reply_perf_config_cache()
    repo = pg_mod.PgContextRepository()
    await repo.insert(Context.model_construct(keywords="kw", time=0, trigger_count=1, answers=[], ban=[], clear_time=0))

    async def _u(i: int):
        await repo.upsert_answer(
            keywords="kw",
            group_id=1,
            answer_keywords="a",
            answer_time=100 + i,
            message=f"m{i}",
            append_on_existing=True,
        )

    await asyncio.gather(*[_u(i) for i in range(20)])

    lite = await repo.find_by_keywords_for_reply("kw")
    full = await repo.find_by_keywords("kw")
    assert lite is not None
    assert full is not None
    assert len(lite.answers[0].messages) == 6
    assert len(full.answers[0].messages) == 20
    assert set(lite.answers[0].messages).issubset(set(full.answers[0].messages))


@pytest.mark.asyncio
async def test_find_by_keywords_for_reply_keeps_bans(pg_engine):
    """接话轻量查询仍需保留 ban 信息，避免提速后放松禁言过滤。"""
    from pallas.core.foundation.db.modules import Ban, Context
    from pallas.core.foundation.db.repository_pg import PgContextRepository

    repo = PgContextRepository()
    await repo.insert(
        Context.model_construct(
            keywords="kw-ban",
            time=100,
            trigger_count=3,
            answers=[],
            ban=[Ban.model_construct(keywords="forbidden", group_id=1, reason="r", time=50)],
            clear_time=9,
        )
    )

    found = await repo.find_by_keywords_for_reply("kw-ban")

    assert found is not None
    assert found.trigger_count == 3
    assert found.clear_time == 9
    assert len(found.ban) == 1
    assert found.ban[0].keywords == "forbidden"
    assert found.ban[0].group_id == 1


@pytest.mark.asyncio
async def test_find_by_keywords_for_reply_uses_two_indexed_read_round_trips(pg_engine):
    from sqlalchemy import event

    from pallas.core.foundation.db.modules import Ban, Context
    from pallas.core.foundation.db.repository_pg import PgContextRepository, clear_reply_query_snapshot_cache

    repo = PgContextRepository()
    await repo.insert(
        Context.model_construct(
            keywords="one-round-trip",
            time=100,
            trigger_count=3,
            answers=[],
            ban=[Ban.model_construct(keywords="forbidden", group_id=1, reason="r", time=50)],
            clear_time=9,
        )
    )
    await repo.upsert_answer("one-round-trip", 1, "answer", 101, "reply", append_on_existing=True)
    await clear_reply_query_snapshot_cache("one-round-trip")
    statements: list[str] = []

    def record_statement(_conn, _cursor, statement, _parameters, _context, _executemany) -> None:
        if statement.lstrip().upper().startswith(("SELECT", "WITH")):
            statements.append(statement)

    event.listen(pg_engine.sync_engine, "before_cursor_execute", record_statement)
    try:
        found = await repo.find_by_keywords_for_reply("one-round-trip")
    finally:
        event.remove(pg_engine.sync_engine, "before_cursor_execute", record_statement)

    assert found is not None
    assert found.answers[0].messages == ["reply"]
    assert [ban.keywords for ban in found.ban] == ["forbidden"]
    assert len(statements) == 2


def test_reply_message_query_limits_to_selected_answer_ids():
    """接话消息查询必须只扫描已入选的 answer_id，不能退回按整个 context 扫描。"""
    from pallas.core.foundation.db import repository_pg as pg_mod

    stmt = pg_mod.build_reply_message_query(answer_ids=[11, 22], msg_cap=8)
    sql = str(stmt.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}))

    assert "context_answer_message.answer_id IN (11, 22)" in sql
    assert "JOIN context_answer" not in sql
    assert "context_answer.context_id" not in sql


def test_message_row_has_group_user_time_index():
    from pallas.core.foundation.db.repository_pg import MessageRow

    index_names = {idx.name for idx in MessageRow.__table__.indexes}
    assert "ix_message_group_user_time" in index_names


def test_context_answer_rows_have_reply_indexes():
    from pallas.core.foundation.db.repository_pg import ContextAnswerMessageRow, ContextAnswerRow

    answer_index_names = {idx.name for idx in ContextAnswerRow.__table__.indexes}
    message_index_names = {idx.name for idx in ContextAnswerMessageRow.__table__.indexes}

    assert "ix_context_answer_context_id" not in answer_index_names
    assert "ix_context_answer_ctx_count_time" in answer_index_names
    assert "ix_context_answer_message_answer_id_id" in message_index_names


@pytest.mark.asyncio
async def test_delete_context_answer_orphans_chunks_large_deletes():
    from pallas.core.foundation.db import repository_pg as mod

    deleted_chunks: list[list[int]] = []

    class FakeResult:
        def __init__(self, rows):
            self._rows = rows

        def scalars(self):
            return self

        def all(self):
            return list(self._rows)

    class FakeSession:
        async def execute(self, stmt):
            sql = str(
                stmt.compile(
                    dialect=postgresql.dialect(),
                    compile_kwargs={"literal_binds": True},
                )
            )
            if sql.startswith("SELECT context_answer.id"):
                return FakeResult(range(1, 2506))
            if sql.startswith("DELETE FROM context_answer"):
                ids = sorted(int(v) for v in stmt._where_criteria[1].right.value)
                deleted_chunks.append(ids)
                return FakeResult([])
            raise AssertionError(sql)

    await mod.delete_context_answer_orphans(FakeSession(), ctx_id=7, kept_ids=[1, 2, 3, 4, 5], chunk_size=1000)

    assert [len(chunk) for chunk in deleted_chunks] == [1000, 1000, 500]
    assert deleted_chunks[0][0] == 6
    assert deleted_chunks[-1][-1] == 2505


def test_ensure_pg_message_group_user_time_index_creates_missing_index(monkeypatch):
    from pallas.core.foundation.db import repository_pg as mod

    executed: list[str] = []

    class FakeInspector:
        def has_table(self, name: str) -> bool:
            return name == "message"

    class FakeConnection:
        def execute(self, statement) -> None:
            executed.append(str(statement))

    monkeypatch.setattr(mod, "inspect", lambda _connection: FakeInspector())

    mod._ensure_pg_message_group_user_time_index(FakeConnection())

    assert executed == ["CREATE INDEX IF NOT EXISTS ix_message_group_user_time ON message (group_id, user_id, time)"]


@pytest.mark.parametrize(
    ("existing_columns", "expected"),
    [
        (
            [],
            [
                "ALTER TABLE llm_memory_entry ADD COLUMN embedding_json TEXT",
                "ALTER TABLE llm_memory_entry ADD COLUMN embedding_model TEXT",
            ],
        ),
        (["embedding_model"], ["ALTER TABLE llm_memory_entry ADD COLUMN embedding_json TEXT"]),
        (["embedding_json", "embedding_model"], []),
    ],
)
def test_ensure_pg_llm_memory_embedding_columns_adds_only_missing_columns(monkeypatch, existing_columns, expected):
    from pallas.core.foundation.db import repository_pg as mod

    executed: list[str] = []

    class FakeInspector:
        def has_table(self, name: str) -> bool:
            return name == "llm_memory_entry"

        def get_columns(self, name: str) -> list[dict[str, str]]:
            assert name == "llm_memory_entry"
            return [{"name": column} for column in existing_columns]

    class FakeConnection:
        def execute(self, statement) -> None:
            executed.append(str(statement))

    monkeypatch.setattr(mod, "inspect", lambda _connection: FakeInspector())

    mod._ensure_pg_llm_memory_embedding_columns(FakeConnection())

    assert executed == expected


@pytest.mark.parametrize(
    ("existing_columns", "expected"),
    [
        (
            [],
            [
                "ALTER TABLE llm_memory_entry ADD COLUMN importance DOUBLE PRECISION NOT NULL DEFAULT 0.5",
                "ALTER TABLE llm_memory_entry ADD COLUMN confidence DOUBLE PRECISION NOT NULL DEFAULT 0.5",
                "ALTER TABLE llm_memory_entry ADD COLUMN expires_at BIGINT NOT NULL DEFAULT 0",
                "ALTER TABLE llm_memory_entry ADD COLUMN visibility TEXT NOT NULL DEFAULT 'private'",
            ],
        ),
        (
            ["importance", "confidence", "expires_at", "visibility"],
            [],
        ),
    ],
)
def test_ensure_pg_llm_memory_metadata_columns_adds_only_missing_columns(monkeypatch, existing_columns, expected):
    from pallas.core.foundation.db import repository_pg as mod

    executed: list[str] = []

    class FakeInspector:
        def has_table(self, name: str) -> bool:
            return name == "llm_memory_entry"

        def get_columns(self, name: str) -> list[dict[str, str]]:
            assert name == "llm_memory_entry"
            return [{"name": column} for column in existing_columns]

    class FakeConnection:
        def execute(self, statement) -> None:
            executed.append(str(statement))

    monkeypatch.setattr(mod, "inspect", lambda _connection: FakeInspector())

    mod._ensure_pg_llm_memory_metadata_columns(FakeConnection())

    assert executed == expected


@pytest.mark.parametrize(
    ("existing_columns", "expected_substrings"),
    [
        (["blob_data"], []),
        (
            ["base64_data"],
            [
                "ADD COLUMN blob_data BYTEA",
                "decode(base64_data, 'base64')",
                "DROP COLUMN base64_data",
            ],
        ),
        (
            ["base64_data", "blob_data"],
            [
                "decode(base64_data, 'base64')",
                "DROP COLUMN base64_data",
            ],
        ),
        ([], ["ADD COLUMN blob_data BYTEA"]),
    ],
)
def test_ensure_pg_image_cache_blob_data_migrates_base64(monkeypatch, existing_columns, expected_substrings):
    from pallas.core.foundation.db import repository_pg as mod

    executed: list[str] = []

    class FakeInspector:
        def has_table(self, name: str) -> bool:
            return name == "image_cache"

        def get_columns(self, name: str) -> list[dict[str, str]]:
            assert name == "image_cache"
            return [{"name": column} for column in existing_columns]

    class FakeConnection:
        def execute(self, statement) -> None:
            executed.append(str(statement))

    monkeypatch.setattr(mod, "inspect", lambda _connection: FakeInspector())

    mod._ensure_pg_image_cache_blob_data(FakeConnection())

    assert len(executed) == len(expected_substrings)
    for sql, needle in zip(executed, expected_substrings, strict=True):
        assert needle in sql


def test_ensure_pg_image_cache_blob_data_skips_missing_table(monkeypatch):
    from pallas.core.foundation.db import repository_pg as mod

    executed: list[str] = []

    class FakeInspector:
        def has_table(self, name: str) -> bool:
            return False

    class FakeConnection:
        def execute(self, statement) -> None:
            executed.append(str(statement))

    monkeypatch.setattr(mod, "inspect", lambda _connection: FakeInspector())

    mod._ensure_pg_image_cache_blob_data(FakeConnection())
    assert executed == []


def test_ensure_pg_context_answer_reply_indexes_create_missing_indexes(monkeypatch):
    from pallas.core.foundation.db import repository_pg as mod

    executed: list[str] = []

    class FakeInspector:
        def has_table(self, name: str) -> bool:
            return name in {"context_answer", "context_answer_message"}

    class FakeConnection:
        def execute(self, statement) -> None:
            executed.append(str(statement))

    monkeypatch.setattr(mod, "inspect", lambda _connection: FakeInspector())

    connection = FakeConnection()
    mod._ensure_pg_context_answer_reply_index(connection)
    mod._ensure_pg_context_answer_message_reply_index(connection)

    assert executed == [
        "DROP INDEX IF EXISTS ix_context_answer_context_id",
        "CREATE INDEX IF NOT EXISTS ix_context_answer_ctx_count_time ON context_answer (context_id, count, time)",
        "CREATE INDEX IF NOT EXISTS ix_context_answer_message_answer_id_id ON context_answer_message (answer_id, id)",
    ]


def test_background_job_rows_have_delivery_claim_index():
    from pallas.core.foundation.db.repository_pg import BackgroundJobRow

    index_names = {idx.name for idx in BackgroundJobRow.__table__.indexes}

    assert "ix_background_job_delivery_claim" in index_names


def test_ensure_pg_background_job_delivery_claim_index(monkeypatch):
    from pallas.core.foundation.db import repository_pg as mod

    executed: list[str] = []

    class FakeInspector:
        def has_table(self, name: str) -> bool:
            return name == "background_job"

    class FakeConnection:
        def execute(self, statement) -> None:
            executed.append(str(statement))

    monkeypatch.setattr(mod, "inspect", lambda _connection: FakeInspector())

    mod._ensure_pg_background_job_delivery_claim_index(FakeConnection())

    assert executed == [
        "CREATE INDEX IF NOT EXISTS ix_background_job_delivery_claim "
        "ON background_job (kind, status, finished_at)"
    ]


def test_ensure_pg_background_job_active_kind_created_index(monkeypatch):
    from pallas.core.foundation.db import repository_pg as mod

    executed: list[str] = []

    class FakeInspector:
        def has_table(self, name: str) -> bool:
            return name == "background_job"

    class FakeConnection:
        def execute(self, statement) -> None:
            executed.append(str(statement))

    monkeypatch.setattr(mod, "inspect", lambda _connection: FakeInspector())

    mod._ensure_pg_background_job_active_kind_created_index(FakeConnection())

    assert executed == [
        "CREATE INDEX IF NOT EXISTS ix_background_job_active_kind_created "
        "ON background_job (kind, created_at) "
        "WHERE finished_at IS NULL AND status IN ('pending', 'leased')"
    ]


@pytest.mark.asyncio
async def test_find_by_keywords_for_reply_many_answers_no_in_overflow(pg_engine, monkeypatch):
    """热词大量 Answer 时不得用超大 IN (...)，接话 find 应成功且受 reply_answers_cap 限制。"""
    from pallas.core.foundation.db import repository_pg as pg_mod
    from pallas.core.foundation.db.modules import Context
    from pallas.product.corpus.reply_perf_config import clear_corpus_reply_perf_config_cache

    monkeypatch.setenv("PALLAS_CORPUS_REPLY_ANSWERS_CAP", "64")
    clear_corpus_reply_perf_config_cache()
    repo = pg_mod.PgContextRepository()
    await repo.insert(
        Context.model_construct(keywords="hot", time=0, trigger_count=1, answers=[], ban=[], clear_time=0)
    )

    for gid in range(80):
        await repo.upsert_answer(
            keywords="hot",
            group_id=gid,
            answer_keywords=f"a{gid}",
            answer_time=100 + gid,
            message=f"m{gid}",
            append_on_existing=True,
        )

    lite = await repo.find_by_keywords_for_reply("hot")
    assert lite is not None
    assert len(lite.answers) <= 64


@pytest.mark.asyncio
async def test_find_by_keywords_for_reply_tightens_caps_for_short_keywords(pg_engine, monkeypatch):
    """超短关键词应进一步收紧候选窗口，避免热点短词把热路径拖长。"""
    from pallas.core.foundation.db import repository_pg as pg_mod
    from pallas.core.foundation.db.modules import Context
    from pallas.product.corpus.reply_perf_config import clear_corpus_reply_perf_config_cache

    monkeypatch.setenv("PALLAS_CORPUS_REPLY_ANSWERS_CAP", "128")
    clear_corpus_reply_perf_config_cache()
    repo = pg_mod.PgContextRepository()
    await repo.insert(Context.model_construct(keywords="hi", time=0, trigger_count=1, answers=[], ban=[], clear_time=0))

    for gid in range(80):
        await repo.upsert_answer(
            keywords="hi",
            group_id=gid,
            answer_keywords=f"a{gid}",
            answer_time=100 + gid,
            message=f"m{gid}",
            append_on_existing=True,
        )

    lite = await repo.find_by_keywords_for_reply("hi")
    assert lite is not None
    assert len(lite.answers) <= 48


@pytest.mark.asyncio
async def test_find_by_keywords_for_reply_reuses_recent_snapshot_during_hot_upsert(pg_engine, monkeypatch):
    """高频 learn 写同一关键词时，接话查询应短暂复用最近快照，避免每条消息都重查。"""
    from pallas.core.foundation.db.modules import Context
    from pallas.core.foundation.db.repository_pg import PgContextRepository
    from pallas.product.corpus.reply_perf_config import clear_corpus_reply_perf_config_cache

    monkeypatch.setenv("PALLAS_CORPUS_REPLY_SNAPSHOT_SEC", "30")
    clear_corpus_reply_perf_config_cache()
    repo = PgContextRepository()
    await repo.insert(
        Context.model_construct(keywords="snap-hot", time=0, trigger_count=1, answers=[], ban=[], clear_time=0)
    )

    await repo.upsert_answer("snap-hot", 1, "a", 100, "first", append_on_existing=True)
    warm = await repo.find_by_keywords_for_reply("snap-hot")
    assert warm is not None
    assert warm.answers[0].messages == ["first"]

    await repo.upsert_answer("snap-hot", 1, "a", 101, "second", append_on_existing=True)
    cached = await repo.find_by_keywords_for_reply("snap-hot")

    assert cached is not None
    assert cached.answers[0].messages == ["first"]


@pytest.mark.asyncio
async def test_find_by_keywords_for_reply_insert_invalidates_recent_miss_snapshot(pg_engine, monkeypatch):
    """新建 Context 后必须能立即打破最近 miss 快照，避免社区回填后仍短暂看不到。"""
    from pallas.core.foundation.db.modules import Context
    from pallas.core.foundation.db.repository_pg import PgContextRepository
    from pallas.product.corpus.reply_perf_config import clear_corpus_reply_perf_config_cache

    monkeypatch.setenv("PALLAS_CORPUS_REPLY_SNAPSHOT_SEC", "30")
    clear_corpus_reply_perf_config_cache()
    repo = PgContextRepository()

    assert await repo.find_by_keywords_for_reply("snap-miss") is None

    await repo.insert(
        Context.model_construct(keywords="snap-miss", time=0, trigger_count=1, answers=[], ban=[], clear_time=0)
    )
    await repo.upsert_answer("snap-miss", 1, "a", 100, "hello", append_on_existing=True)
    found = await repo.find_by_keywords_for_reply("snap-miss")

    assert found is not None
    assert found.answers[0].messages == ["hello"]


@pytest.mark.asyncio
async def test_append_ban_invalidates_recent_reply_snapshot(pg_engine, monkeypatch):
    """ban 追加后应立即刷新快照，不能让旧快照继续放行刚禁掉的答案。"""
    from pallas.core.foundation.db.modules import Ban, Context
    from pallas.core.foundation.db.repository_pg import PgContextRepository
    from pallas.product.corpus.reply_perf_config import clear_corpus_reply_perf_config_cache

    monkeypatch.setenv("PALLAS_CORPUS_REPLY_SNAPSHOT_SEC", "30")
    clear_corpus_reply_perf_config_cache()
    repo = PgContextRepository()
    await repo.insert(
        Context.model_construct(keywords="snap-ban", time=0, trigger_count=1, answers=[], ban=[], clear_time=0)
    )
    await repo.upsert_answer("snap-ban", 1, "a", 100, "hello", append_on_existing=True)
    warm = await repo.find_by_keywords_for_reply("snap-ban")
    assert warm is not None
    assert warm.ban == []

    await repo.append_ban("snap-ban", Ban.model_construct(keywords="a", group_id=1, reason="r", time=101))
    refreshed = await repo.find_by_keywords_for_reply("snap-ban")

    assert refreshed is not None
    assert [ban.keywords for ban in refreshed.ban] == ["a"]


@pytest.mark.asyncio
async def test_find_ban_reply_target(pg_engine):
    """按 group_id + reply 原文应能精确反查 ban 目标。"""
    from pallas.core.foundation.db.modules import Context
    from pallas.core.foundation.db.repository_pg import PgContextRepository

    repo = PgContextRepository()
    await repo.insert(
        Context.model_construct(
            keywords="pre-kw",
            time=0,
            trigger_count=1,
            answers=[],
            ban=[],
            clear_time=0,
        )
    )
    await repo.upsert_answer(
        "pre-kw",
        733291779,
        "reply-kw",
        100,
        "群友耀.原星(1101088091)退群了!",
        append_on_existing=True,
    )

    found = await repo.find_ban_reply_target(733291779, "群友耀.原星(1101088091)退群了!")

    assert found == ("pre-kw", "reply-kw")


@pytest.mark.asyncio
async def test_upsert_answer_append_flag(pg_engine):
    """append_on_existing=False 时 count 仍 +1，但不把新 message 追加到已有 Answer。"""
    from pallas.core.foundation.db.modules import Context
    from pallas.core.foundation.db.repository_pg import PgContextRepository

    repo = PgContextRepository()
    await repo.insert(Context.model_construct(keywords="k", time=0, trigger_count=1, answers=[], ban=[], clear_time=0))

    await repo.upsert_answer("k", 1, "a", 100, "first", append_on_existing=True)
    await repo.upsert_answer("k", 1, "a", 200, "second", append_on_existing=False)
    found = await repo.find_by_keywords("k")
    assert found is not None
    assert found.answers[0].count == 2
    assert found.answers[0].time == 200
    assert "first" in found.answers[0].messages
    assert "second" not in found.answers[0].messages


@pytest.mark.asyncio
async def test_upsert_answer_context_missing(pg_engine):
    """Context 不存在时 upsert_answer 必须 no-op，不得凭空造 Context。"""
    from pallas.core.foundation.db.repository_pg import PgContextRepository

    repo = PgContextRepository()
    await repo.upsert_answer("absent", 1, "a", 100, "m", append_on_existing=True)
    found = await repo.find_by_keywords("absent")
    assert found is None


@pytest.mark.asyncio
async def test_learn_answer_creates_context_when_missing(pg_engine):
    """learn_answer 缺 Context 时应直接建 Context + 首条 Answer，避免先 exists 再 insert。"""
    from pallas.core.foundation.db.repository_pg import PgContextRepository

    repo = PgContextRepository()
    created = await repo.learn_answer(
        keywords="learn-missing",
        group_id=1,
        answer_keywords="ans",
        answer_time=100,
        message="msg",
        append_on_existing=False,
    )

    assert created is True
    found = await repo.find_by_keywords("learn-missing")
    assert found is not None
    assert found.trigger_count == 1
    assert len(found.answers) == 1
    assert found.answers[0].keywords == "ans"
    assert found.answers[0].count == 1
    assert found.answers[0].messages == ["msg"]


@pytest.mark.asyncio
async def test_learn_answer_blocks_contaminated_message(pg_engine, monkeypatch) -> None:
    from pallas.core.foundation.db.repository_pg import PgContextRepository
    from pallas.product.llm.config import LlmConfig

    monkeypatch.setattr(
        "pallas.product.llm.config.get_llm_config",
        lambda: LlmConfig(llm_corpus_learn_guard_enabled=True),
    )
    repo = PgContextRepository()
    created = await repo.learn_answer(
        keywords="learn-blocked",
        group_id=1,
        answer_keywords="ans",
        answer_time=100,
        message="希望每个庆典都能顺利举行",
        append_on_existing=False,
    )
    assert created is False
    assert await repo.find_by_keywords("learn-blocked") is None


@pytest.mark.asyncio
async def test_learn_answer_updates_existing_context(pg_engine):
    """learn_answer 命中已存在 Context 时应原子累加 trigger_count / answer.count。"""
    from pallas.core.foundation.db.modules import Context
    from pallas.core.foundation.db.repository_pg import PgContextRepository

    repo = PgContextRepository()
    await repo.insert(
        Context.model_construct(keywords="learn-hit", time=0, trigger_count=1, answers=[], ban=[], clear_time=0)
    )

    created = await repo.learn_answer(
        keywords="learn-hit",
        group_id=1,
        answer_keywords="ans",
        answer_time=100,
        message="first",
        append_on_existing=True,
    )
    created_again = await repo.learn_answer(
        keywords="learn-hit",
        group_id=1,
        answer_keywords="ans",
        answer_time=200,
        message="second",
        append_on_existing=False,
    )

    assert created is False
    assert created_again is False
    found = await repo.find_by_keywords("learn-hit")
    assert found is not None
    assert found.trigger_count == 3
    assert found.answers[0].count == 2
    assert found.answers[0].time == 200
    assert "first" in found.answers[0].messages
    assert "second" not in found.answers[0].messages


@pytest.mark.asyncio
async def test_delete_expired_chunked(pg_engine):
    """delete_expired 分块模式下应清掉所有过期行、保留未过期行。"""
    from pallas.core.foundation.db.modules import Context
    from pallas.core.foundation.db.repository_pg import PgContextRepository

    repo = PgContextRepository()
    for i in range(100):
        await repo.insert(
            Context.model_construct(keywords=f"old{i}", time=10, trigger_count=1, answers=[], ban=[], clear_time=0)
        )
    await repo.insert(
        Context.model_construct(keywords="keep", time=9999, trigger_count=1, answers=[], ban=[], clear_time=0)
    )

    await repo.delete_expired(expiration=100, threshold=3)
    assert await repo.find_by_keywords("old0") is None
    assert await repo.find_by_keywords("old99") is None
    assert await repo.find_by_keywords("keep") is not None


@pytest.mark.asyncio
async def test_null_byte_stripping(pg_engine):
    """Context / Answer / Ban / Message 全链路入库前都剥除 \\x00，PG 不得因此报错。"""
    from pallas.core.foundation.db.modules import Answer, Ban, Context, Message
    from pallas.core.foundation.db.repository_pg import PgContextRepository, PgMessageRepository

    ctx_repo = PgContextRepository()
    msg_repo = PgMessageRepository()

    await ctx_repo.insert(
        Context.model_construct(
            keywords="null\x00kw",
            time=0,
            trigger_count=1,
            answers=[Answer.model_construct(keywords="a\x00", group_id=1, count=1, time=0, messages=["m\x00sg"])],
            ban=[Ban.model_construct(keywords="b\x00", group_id=1, reason="r\x00", time=0)],
            clear_time=0,
        )
    )
    found = await ctx_repo.find_by_keywords("null\x00kw")
    assert found is not None
    assert "\x00" not in found.keywords
    assert "\x00" not in found.answers[0].keywords
    assert "\x00" not in found.answers[0].messages[0]
    assert "\x00" not in found.ban[0].keywords
    assert "\x00" not in found.ban[0].reason

    # bulk_insert 也必须接受带 \x00 的字段，不抛 StringDataError
    await msg_repo.bulk_insert([
        Message.model_construct(
            group_id=1,
            user_id=2,
            bot_id=3,
            raw_message="raw\x00",
            is_plain_text=True,
            plain_text="plain\x00",
            keywords="kw\x00",
            time=0,
        )
    ])


@pytest.mark.asyncio
async def test_message_find_recent_in_group(pg_engine):
    from pallas.core.foundation.db.modules import Message
    from pallas.core.foundation.db.repository_pg import PgMessageRepository

    repo = PgMessageRepository()
    gid = 88001
    await repo.bulk_insert([
        Message.model_construct(
            group_id=gid,
            user_id=10,
            bot_id=1,
            raw_message="a",
            is_plain_text=True,
            plain_text="a",
            keywords="a",
            time=100,
        ),
        Message.model_construct(
            group_id=gid,
            user_id=20,
            bot_id=1,
            raw_message="b",
            is_plain_text=True,
            plain_text="b",
            keywords="b",
            time=200,
        ),
    ])
    rows = await repo.find_recent_in_group(gid, before_time=250, limit=8)

    assert [row.plain_text for row in rows] == ["a", "b"]
    one = await repo.find_recent_in_group(gid, before_time=250, user_id=20, limit=1)
    assert len(one) == 1
    assert one[0].plain_text == "b"


@pytest.mark.asyncio
async def test_message_find_recent_in_group_keeps_timeline_metadata(pg_engine):
    from pallas.core.foundation.db.modules import Message
    from pallas.core.foundation.db.repository_pg import PgMessageRepository

    repo = PgMessageRepository()
    await repo.bulk_insert([
        Message.model_construct(
            group_id=88002,
            user_id=10,
            bot_id=1,
            raw_message="[CQ:reply,id=90]还是笨蛋欸",
            is_plain_text=True,
            plain_text="还是笨蛋欸",
            keywords="笨蛋",
            sender_name="兔兔",
            message_id=101,
            reply_to_message_id=90,
            time=100,
        )
    ])

    row = (await repo.find_recent_in_group(88002))[0]
    assert row.plain_text == "还是笨蛋欸"
    assert row.sender_name == "兔兔"
    assert row.message_id == 101
    assert row.reply_to_message_id == 90


@pytest.mark.asyncio
async def test_upsert_answer_handles_long_keywords(pg_engine):
    """answer.keywords 超出 btree 2704 字节上限时，UNIQUE 约束走 keywords_hash，不应触发 ProgramLimitExceededError。"""
    from pallas.core.foundation.db.modules import Context
    from pallas.core.foundation.db.repository_pg import PgContextRepository

    repo = PgContextRepository()
    await repo.insert(
        Context.model_construct(keywords="longkw", time=0, trigger_count=1, answers=[], ban=[], clear_time=0)
    )
    long_ak = "x" * 5000  # 远超 btree 单行 2704 字节硬上限
    await repo.upsert_answer("longkw", 1, long_ak, 100, "m1", append_on_existing=True)
    await repo.upsert_answer("longkw", 1, long_ak, 200, "m2", append_on_existing=True)

    found = await repo.find_by_keywords("longkw")
    assert found is not None
    assert len(found.answers) == 1
    assert found.answers[0].keywords == long_ak
    assert found.answers[0].count == 2


@pytest.mark.asyncio
async def test_blacklist_upsert_is_atomic(pg_engine):
    """并发 upsert_answers 到同一 group_id 不会炸库、最终只剩 1 行。"""
    from pallas.core.foundation.db.repository_pg import PgBlackListRepository

    repo = PgBlackListRepository()
    await asyncio.gather(*[repo.upsert_answers(1, [f"a{i}"]) for i in range(20)])
    all_bl = await repo.find_all()
    group_rows = [x for x in all_bl if x.group_id == 1]
    assert len(group_rows) == 1


@pytest.mark.asyncio
async def test_blacklist_answers_and_reserve_do_not_clobber(pg_engine):
    """同一 group_id 下 upsert_answers 与 upsert_answers_reserve 各管各的列，互不覆盖。"""
    from pallas.core.foundation.db.repository_pg import PgBlackListRepository

    repo = PgBlackListRepository()
    # 先写 answers，再写 reserve；reserve 分支不应把 answers 清空
    await repo.upsert_answers(77, ["a", "b"])
    await repo.upsert_answers_reserve(77, ["ra", "rb"])
    rows = [r for r in await repo.find_all() if r.group_id == 77]
    assert len(rows) == 1
    assert sorted(rows[0].answers) == ["a", "b"]
    assert sorted(rows[0].answers_reserve) == ["ra", "rb"]

    # 反向：已有 reserve 的行，再追加 answers 也不能覆盖 reserve
    await repo.upsert_answers_reserve(88, ["only_reserve"])
    await repo.upsert_answers(88, ["a2"])
    rows = [r for r in await repo.find_all() if r.group_id == 88]
    assert len(rows) == 1
    assert rows[0].answers == ["a2"]
    assert rows[0].answers_reserve == ["only_reserve"]


@pytest.mark.asyncio
async def test_blacklist_upsert_many(pg_engine):
    """批量 upsert 多群黑名单：一次写多群，answers 与 answers_reserve 同时落库。"""
    from pallas.core.foundation.db.modules import BlackList
    from pallas.core.foundation.db.repository_pg import PgBlackListRepository

    repo = PgBlackListRepository()
    await repo.upsert_many_blacklist([
        BlackList.model_construct(group_id=1, answers=["a", "b"], answers_reserve=["r1"]),
        BlackList.model_construct(group_id=2, answers=["c"], answers_reserve=[]),
    ])
    rows = {r.group_id: r for r in await repo.find_all()}
    assert sorted(rows[1].answers) == ["a", "b"]
    assert rows[1].answers_reserve == ["r1"]
    assert rows[2].answers == ["c"]
    assert rows[2].answers_reserve == []

    # 再次批量 upsert：覆盖两列，不新增行
    await repo.upsert_many_blacklist([
        BlackList.model_construct(group_id=1, answers=["b", "c"], answers_reserve=["r2"])
    ])
    rows = {r.group_id: r for r in await repo.find_all()}
    assert sorted(rows[1].answers) == ["b", "c"]
    assert rows[1].answers_reserve == ["r2"]
    assert len(rows) == 2


@pytest.mark.asyncio
async def test_image_cache_save_is_upsert(pg_engine):
    """PgImageCacheRepository.save 必须对齐 Mongo save() 的 upsert 语义。

    字段名变更（base64_data → blob_data）+ 类型变 BYTEA（issue #223）。
    """
    from pallas.core.foundation.db.modules import ImageCache
    from pallas.core.foundation.db.repository_pg import PgImageCacheRepository

    repo = PgImageCacheRepository()
    ic = ImageCache.model_construct(cq_code="[CQ:image,file=x.image]", blob_data=None, ref_times=1, date=20250419)
    await repo.save(ic)
    assert await repo.find_by_cq_code("[CQ:image,file=x.image]") is not None

    ic.ref_times = 5
    ic.blob_data = b"\x89PNG\r\n\x1a\n"
    await repo.save(ic)
    got = await repo.find_by_cq_code("[CQ:image,file=x.image]")
    assert got is not None
    assert got.ref_times == 5
    assert got.blob_data == b"\x89PNG\r\n\x1a\n"


@pytest.mark.asyncio
async def test_image_cache_insert_is_no_op_on_duplicate(pg_engine):
    """insert() 的契约是并发下同 cq_code 第二次写等价 no-op，原行不得被覆盖。"""
    from pallas.core.foundation.db.modules import ImageCache
    from pallas.core.foundation.db.repository_pg import PgImageCacheRepository

    repo = PgImageCacheRepository()
    first = ImageCache.model_construct(cq_code="[CQ:image,file=dup.image]", blob_data=b"v1", ref_times=1, date=20250419)
    await repo.insert(first)

    # 第二次 insert 应被 ON CONFLICT DO NOTHING 吃掉，原有值保持不变
    second = ImageCache.model_construct(
        cq_code="[CQ:image,file=dup.image]", blob_data=b"v2", ref_times=99, date=20260101
    )
    await repo.insert(second)

    got = await repo.find_by_cq_code("[CQ:image,file=dup.image]")
    assert got is not None
    assert got.blob_data == b"v1"
    assert got.ref_times == 1
    assert got.date == 20250419


@pytest.mark.asyncio
async def test_image_cache_touch_increments_ref_and_refreshes_date_without_replacing_blob(pg_engine):
    from pallas.core.foundation.db.modules import ImageCache
    from pallas.core.foundation.db.repository_pg import PgImageCacheRepository

    repo = PgImageCacheRepository()
    await repo.insert(ImageCache.model_construct(cq_code="touch", blob_data=b"original", ref_times=1, date=20260101))

    await repo.touch("touch", date=20260810)

    found = await repo.find_by_cq_code("touch")
    assert found is not None
    assert found.ref_times == 2
    assert found.date == 20260810
    assert found.blob_data == b"original"


@pytest.mark.asyncio
async def test_image_cache_content_hash_lookup_selects_one_row_when_cache_keys_share_bytes(monkeypatch):
    from types import SimpleNamespace

    from sqlalchemy.exc import MultipleResultsFound

    from pallas.core.foundation.db import repository_pg

    row = SimpleNamespace(
        cq_code="[CQ:image,file=latest-private.image,user_id=10087]",
        content_hash="a" * 64,
        blob_data=b"same-sticker-bytes",
        blob_path=None,
        blob_size=None,
        ref_times=1,
        date=20260811,
    )

    class DuplicateHashResult:
        def scalar_one_or_none(self):
            raise MultipleResultsFound("Multiple rows were found when one or none was required")

        def scalars(self):
            return SimpleNamespace(first=lambda: row)

    class Session:
        statement = None

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def execute(self, statement):
            self.statement = statement
            return DuplicateHashResult()

    session = Session()
    monkeypatch.setattr(repository_pg, "get_session", lambda **_kwargs: session)

    found = await repository_pg.PgImageCacheRepository().find_by_content_hash("a" * 64)

    assert found is not None
    assert found.blob_data == b"same-sticker-bytes"
    assert "CQ:" not in repr(found.model_dump(exclude={"cq_code"}))
    sql = str(session.statement.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}))
    assert "ORDER BY image_cache.date DESC, image_cache.id DESC" in sql
    assert "LIMIT 1" in sql


@pytest.mark.asyncio
async def test_image_cache_find_latest_with_blob_skips_empty_entries(pg_engine):
    from pallas.core.foundation.db.modules import ImageCache
    from pallas.core.foundation.db.repository_pg import PgImageCacheRepository

    repo = PgImageCacheRepository()
    await repo.insert(
        ImageCache.model_construct(cq_code="[CQ:image,file=empty.image]", blob_data=None, ref_times=9, date=20260806)
    )
    await repo.insert(
        ImageCache.model_construct(
            cq_code="[CQ:image,file=ready.image]", blob_data=b"image", ref_times=1, date=20260805
        )
    )

    found = await repo.find_latest_with_blob()

    assert found is not None
    assert found.cq_code == "[CQ:image,file=ready.image]"
    assert found.blob_data == b"image"


@pytest.mark.asyncio
async def test_sticker_label_worker_resolves_duplicate_content_hash_without_cq_leak(pg_engine, monkeypatch):
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    from pallas.core.foundation.db.modules import ImageCache
    from pallas.core.foundation.db.repository_pg import PgImageCacheRepository
    from pallas.product.llm import sticker_label_jobs
    from pallas.product.llm.sticker_labels import StickerSemanticLabel, content_hash_for_bytes

    content = b"same-sticker-bytes"
    content_hash = content_hash_for_bytes(content)
    older_cq = "[CQ:image,file=older-private.image,user_id=10086]"
    newer_cq = "[CQ:image,file=newer-private.image,user_id=10087]"
    repo = PgImageCacheRepository()
    await repo.insert(
        ImageCache.model_construct(
            cq_code=older_cq, content_hash=content_hash, blob_data=content, ref_times=1, date=20260810
        )
    )
    await repo.insert(
        ImageCache.model_construct(
            cq_code=newer_cq, content_hash=content_hash, blob_data=content, ref_times=1, date=20260811
        )
    )

    monkeypatch.setattr("pallas.core.shared.utils.media_cache.image_cache_repo", repo)
    label = StickerSemanticLabel(content_hash=content_hash, is_sticker=True, confidence=0.9, prompt_version=1)
    vision = AsyncMock(return_value=(label, "provider", "model"))
    save_observation = AsyncMock()
    labels = SimpleNamespace(upsert=AsyncMock())
    monkeypatch.setattr(sticker_label_jobs, "label_sticker_with_vision", vision)
    monkeypatch.setattr(sticker_label_jobs, "save_sticker_label_observation", save_observation)
    monkeypatch.setattr(sticker_label_jobs, "sticker_label_repository", lambda: labels)

    await sticker_label_jobs.handle_sticker_label_visual({
        "job_id": "duplicate-hash",
        "content_hash": content_hash,
        "source": "manual_sticker",
        "observation": {"state": "queued"},
    })

    vision.assert_awaited_once_with(content)
    labels.upsert.assert_awaited_once_with(label)
    serialized = repr(save_observation.await_args.args)
    assert "CQ:" not in serialized
    assert older_cq not in serialized
    assert newer_cq not in serialized


@pytest.mark.asyncio
async def test_image_cache_prune_applies_retention_tiers_and_byte_limit(pg_engine):
    from pallas.core.foundation.db.modules import ImageCache
    from pallas.core.foundation.db.repository import ImageCachePrunePolicy
    from pallas.core.foundation.db.repository_pg import PgImageCacheRepository

    repo = PgImageCacheRepository()
    rows = [
        ImageCache.model_construct(cq_code="absolute-old", blob_data=b"a" * 4, ref_times=9, date=20260101),
        ImageCache.model_construct(cq_code="single-old", blob_data=b"b" * 4, ref_times=1, date=20260701),
        ImageCache.model_construct(cq_code="single-new", blob_data=b"c" * 4, ref_times=1, date=20260801),
        ImageCache.model_construct(cq_code="popular-oldest", blob_data=b"d" * 4, ref_times=5, date=20260720),
        ImageCache.model_construct(cq_code="popular-newest", blob_data=b"e" * 4, ref_times=5, date=20260802),
    ]
    for row in rows:
        await repo.insert(row)

    result = await repo.prune(
        ImageCachePrunePolicy(
            single_use_before=20260711,
            absolute_before=20260512,
            max_blob_bytes=10,
            batch_size=2,
        )
    )

    assert result.deleted_rows == 3
    # 容量上限按整行删除，最终可能低于 max_blob_bytes。
    assert result.deleted_blob_bytes == 12
    assert result.remaining_blob_bytes == 8
    assert await repo.find_by_cq_code("absolute-old") is None
    assert await repo.find_by_cq_code("single-old") is None
    assert await repo.find_by_cq_code("single-new") is None
    assert await repo.find_by_cq_code("popular-oldest") is not None
    assert await repo.find_by_cq_code("popular-newest") is not None


def _observe_image_cache_race_sessions(
    monkeypatch,
    *,
    candidate_locked=None,
    resume_candidate=None,
    touch_started=None,
    touch_updated=None,
    resume_touch=None,
):
    from contextlib import asynccontextmanager

    from sqlalchemy import text

    from pallas.core.foundation.db import repository_pg

    original_get_session = repository_pg.get_session
    observed = {"candidate_pids": [], "touch_pids": []}
    candidate_pause_used = False

    class SessionProbe:
        def __init__(self, session):
            self.session = session

        def __getattr__(self, name):
            return getattr(self.session, name)

        async def execute(self, statement, *args, **kwargs):
            nonlocal candidate_pause_used
            if getattr(statement, "_for_update_arg", None) is not None:
                pid = await self.session.scalar(text("SELECT pg_backend_pid()"))
                observed["candidate_pids"].append(pid)
                result = await self.session.execute(statement, *args, **kwargs)
                if candidate_locked is not None and not candidate_pause_used:
                    candidate_pause_used = True
                    candidate_locked.set()
                    await resume_candidate.wait()
                return result
            if type(statement).__name__ == "Update" and statement.table.name == "image_cache":
                pid = await self.session.scalar(text("SELECT pg_backend_pid()"))
                observed["touch_pids"].append(pid)
                if touch_started is not None:
                    touch_started.set()
                result = await self.session.execute(statement, *args, **kwargs)
                if touch_updated is not None:
                    touch_updated.set()
                    await resume_touch.wait()
                return result
            return await self.session.execute(statement, *args, **kwargs)

    @asynccontextmanager
    async def observed_get_session(*, read_only=False):
        async with original_get_session(read_only=read_only) as session:
            yield SessionProbe(session)

    monkeypatch.setattr(repository_pg, "get_session", observed_get_session)
    return observed


@pytest.mark.asyncio
async def test_image_cache_prune_skips_row_locked_by_touch_and_rechecks_after_commit(pg_engine, monkeypatch):
    from pallas.core.foundation.db.modules import ImageCache
    from pallas.core.foundation.db.repository import ImageCachePrunePolicy
    from pallas.core.foundation.db.repository_pg import PgImageCacheRepository

    repo = PgImageCacheRepository()
    await repo.insert(
        ImageCache.model_construct(cq_code="touch-prune-order", blob_data=None, ref_times=1, date=20260101)
    )
    touch_updated = asyncio.Event()
    resume_touch = asyncio.Event()
    observed = _observe_image_cache_race_sessions(
        monkeypatch,
        touch_updated=touch_updated,
        resume_touch=resume_touch,
    )
    policy = ImageCachePrunePolicy(
        single_use_before=20260801,
        absolute_before=20260801,
        max_blob_bytes=1000,
        batch_size=10,
    )

    touch_task = asyncio.create_task(repo.touch("touch-prune-order", date=20260810))
    try:
        await asyncio.wait_for(touch_updated.wait(), timeout=5)
        while_touch_uncommitted = await asyncio.wait_for(repo.prune(policy), timeout=5)
        assert while_touch_uncommitted.deleted_rows == 0
        assert observed["candidate_pids"]
        assert observed["candidate_pids"][0] != observed["touch_pids"][0]
    finally:
        resume_touch.set()
        await asyncio.wait_for(asyncio.gather(touch_task, return_exceptions=True), timeout=5)

    after_touch_commit = await asyncio.wait_for(repo.prune(policy), timeout=5)
    found = await repo.find_by_cq_code("touch-prune-order")
    touch_task.result()
    assert after_touch_commit.deleted_rows == 0
    assert found is not None
    assert found.ref_times == 2
    assert found.date == 20260810


@pytest.mark.asyncio
async def test_image_cache_prune_holds_row_lock_before_touch_without_deadlock(pg_engine, monkeypatch):
    from sqlalchemy import text

    from pallas.core.foundation.db.modules import ImageCache
    from pallas.core.foundation.db.repository import ImageCachePrunePolicy
    from pallas.core.foundation.db.repository_pg import PgImageCacheRepository

    repo = PgImageCacheRepository()
    await repo.insert(
        ImageCache.model_construct(cq_code="prune-touch-order", blob_data=None, ref_times=1, date=20260101)
    )
    candidate_locked = asyncio.Event()
    resume_prune = asyncio.Event()
    touch_started = asyncio.Event()
    observed = _observe_image_cache_race_sessions(
        monkeypatch,
        candidate_locked=candidate_locked,
        resume_candidate=resume_prune,
        touch_started=touch_started,
    )
    policy = ImageCachePrunePolicy(
        single_use_before=20260801,
        absolute_before=20260801,
        max_blob_bytes=1000,
        batch_size=10,
    )
    prune_task = asyncio.create_task(repo.prune(policy))
    touch_task = None
    try:
        await asyncio.wait_for(candidate_locked.wait(), timeout=5)
        touch_task = asyncio.create_task(repo.touch("prune-touch-order", date=20260810))
        await asyncio.wait_for(touch_started.wait(), timeout=5)
        touch_pid = observed["touch_pids"][0]

        async def wait_until_touch_is_blocked():
            async with pg_engine.connect() as monitor:
                while True:
                    wait_type = await monitor.scalar(
                        text("SELECT wait_event_type FROM pg_stat_activity WHERE pid = :pid"),
                        {"pid": touch_pid},
                    )
                    if wait_type == "Lock":
                        return
                    await asyncio.sleep(0.01)

        await asyncio.wait_for(wait_until_touch_is_blocked(), timeout=5)
        assert observed["candidate_pids"]
        assert observed["candidate_pids"][0] != touch_pid
    finally:
        resume_prune.set()
        pending = [task for task in (prune_task, touch_task) if task is not None]
        await asyncio.wait_for(asyncio.gather(*pending, return_exceptions=True), timeout=5)

    prune_result = prune_task.result()
    assert touch_task is not None
    touch_task.result()
    assert prune_result.deleted_rows == 1
    assert await repo.find_by_cq_code("prune-touch-order") is None


@pytest.mark.asyncio
async def test_image_cache_concurrent_prune_counts_delete_once(pg_engine, monkeypatch):
    from sqlalchemy import update

    from pallas.core.foundation.db import repository_pg as pg_mod
    from pallas.core.foundation.db.modules import ImageCache
    from pallas.core.foundation.db.repository import ImageCachePrunePolicy
    from pallas.core.foundation.db.repository_pg import PgImageCacheRepository
    from pallas.core.foundation.db.repository_pg.schema import ImageCacheRow

    repo = PgImageCacheRepository()
    await repo.insert(ImageCache.model_construct(cq_code="double-prune", blob_data=None, ref_times=1, date=20260101))
    async with pg_mod.get_session() as session:
        await session.execute(update(ImageCacheRow).where(ImageCacheRow.cq_code == "double-prune").values(blob_size=13))
        await session.commit()

    candidate_locked = asyncio.Event()
    resume_prune = asyncio.Event()
    observed = _observe_image_cache_race_sessions(
        monkeypatch,
        candidate_locked=candidate_locked,
        resume_candidate=resume_prune,
    )
    policy = ImageCachePrunePolicy(
        single_use_before=20260801,
        absolute_before=20260801,
        max_blob_bytes=1000,
        batch_size=10,
    )
    first_prune = asyncio.create_task(repo.prune(policy))
    try:
        await asyncio.wait_for(candidate_locked.wait(), timeout=5)
        second_result = await asyncio.wait_for(repo.prune(policy), timeout=5)
        assert second_result.deleted_rows == 0
        assert second_result.deleted_blob_bytes == 0
        assert len(observed["candidate_pids"]) == 2
        assert observed["candidate_pids"][0] != observed["candidate_pids"][1]
    finally:
        resume_prune.set()
        await asyncio.wait_for(asyncio.gather(first_prune, return_exceptions=True), timeout=5)

    first_result = first_prune.result()
    assert first_result.deleted_rows == 1
    assert first_result.deleted_blob_bytes == 13
    assert first_result.deleted_rows + second_result.deleted_rows == 1
    assert first_result.deleted_blob_bytes + second_result.deleted_blob_bytes == 13


def _image_blob_lock_key(content_hash: str) -> int:
    import hashlib

    return int.from_bytes(hashlib.sha256(content_hash.encode()).digest()[:4], "big", signed=True)


async def _wait_for_image_blob_lock_waiters(engine, content_hash: str, count: int, *, tasks=()) -> set[int]:
    from sqlalchemy import text

    namespace = 0x50414C4C
    lock_key = _image_blob_lock_key(content_hash) & 0xFFFFFFFF
    async with engine.connect() as monitor:
        for _ in range(250):
            for task in tasks:
                if task.done():
                    task.result()
                    raise AssertionError("image-cache operation completed before waiting for its blob lock")
            await monitor.execute(text("SELECT pg_stat_clear_snapshot()"))
            result = await monitor.execute(
                text(
                    "SELECT DISTINCT pid FROM pg_locks WHERE locktype = 'advisory' AND NOT granted "
                    "AND database = (SELECT oid FROM pg_database WHERE datname = current_database()) "
                    "AND classid = CAST(:namespace AS oid) AND objid = CAST(:key AS oid) "
                    "AND objsubid = 2 AND pid <> pg_backend_pid()"
                ),
                {"namespace": namespace, "key": lock_key},
            )
            pids = set(result.scalars().all())
            if len(pids) >= count:
                return pids
            await asyncio.sleep(0.02)
    raise AssertionError(f"expected {count} PostgreSQL waiters for image blob lock [{content_hash}]")


async def _wait_for_image_cache_row_lock_waiter(engine, *, tasks=()) -> None:
    from sqlalchemy import text

    async with engine.connect() as monitor:
        for _ in range(250):
            for task in tasks:
                if task.done():
                    task.result()
                    raise AssertionError("image-cache operation completed before waiting for its row lock")
            await monitor.execute(text("SELECT pg_stat_clear_snapshot()"))
            result = await monitor.execute(
                text(
                    "SELECT pid FROM pg_stat_activity WHERE datname = current_database() "
                    "AND pid <> pg_backend_pid() AND wait_event_type = 'Lock' "
                    "AND query ILIKE '%FROM image_cache%' AND query ILIKE '%FOR UPDATE%'"
                )
            )
            if result.first() is not None:
                return
            await asyncio.sleep(0.02)
    raise AssertionError("expected a PostgreSQL image_cache row-lock waiter")


def _isolate_image_blob_files(tmp_path, monkeypatch):
    from pallas.core.foundation.db import blob_store

    monkeypatch.setattr(blob_store, "DATA_ROOT", tmp_path)
    monkeypatch.setattr(blob_store, "_BLOB_ROOT", tmp_path / blob_store.BLOB_ROOT_NAME)


@pytest.mark.asyncio
async def test_image_cache_save_and_independent_blob_gc_share_pg_hash_lock(pg_engine, tmp_path, monkeypatch):
    import hashlib

    from sqlalchemy import text

    from pallas.core.foundation.db import blob_store, repository_pg
    from pallas.core.foundation.db.lifecycle_adapters import PostgresLifecycleAdapter
    from pallas.core.foundation.db.modules import ImageCache
    from pallas.core.foundation.db.repository_pg import PgImageCacheRepository

    _isolate_image_blob_files(tmp_path, monkeypatch)
    content = b"shared image blob"
    content_hash = hashlib.sha256(content).hexdigest()
    blob_store.write_image_blob(content_hash, content)
    repo = PgImageCacheRepository()
    adapter = PostgresLifecycleAdapter()
    save_task = None
    insert_task = None
    hash_only_task = None
    hash_only_insert_task = None
    gc_task = None

    async with repository_pg.get_session() as holder:
        await holder.execute(
            text("SELECT pg_advisory_xact_lock(:namespace, :key)"),
            {"namespace": 0x50414C4C, "key": _image_blob_lock_key(content_hash)},
        )
        holder_pid = await holder.scalar(text("SELECT pg_backend_pid()"))
        save_task = asyncio.create_task(
            repo.save(
                ImageCache.model_construct(
                    cq_code="locked-save", content_hash=content_hash, blob_data=content, ref_times=1, date=20261103
                )
            )
        )
        insert_task = asyncio.create_task(
            repo.insert(
                ImageCache.model_construct(
                    cq_code="locked-insert", content_hash=content_hash, blob_data=content, ref_times=1, date=20261103
                )
            )
        )
        hash_only_task = asyncio.create_task(
            repo.save(
                ImageCache.model_construct(
                    cq_code="locked-hash-only",
                    content_hash=f"{content_hash}\x00",
                    blob_data=None,
                    ref_times=1,
                    date=20261103,
                )
            )
        )
        hash_only_insert_task = asyncio.create_task(
            repo.insert(
                ImageCache.model_construct(
                    cq_code="locked-hash-only-insert",
                    content_hash=content_hash,
                    blob_data=None,
                    ref_times=1,
                    date=20261103,
                )
            )
        )
        gc_task = asyncio.create_task(adapter.prune_image_cache_files())
        try:
            waiter_pids = await _wait_for_image_blob_lock_waiters(
                pg_engine,
                content_hash,
                5,
                tasks=(save_task, insert_task, hash_only_task, hash_only_insert_task, gc_task),
            )
            assert holder_pid not in waiter_pids
            assert not save_task.done()
            assert not insert_task.done()
            assert not hash_only_task.done()
            assert not hash_only_insert_task.done()
            assert not gc_task.done()
            assert blob_store.read_image_blob(content_hash) == content
        finally:
            await holder.commit()
            await asyncio.wait_for(
                asyncio.gather(
                    save_task, insert_task, hash_only_task, hash_only_insert_task, gc_task, return_exceptions=True
                ),
                timeout=5,
            )

    save_task.result()
    insert_task.result()
    hash_only_task.result()
    hash_only_insert_task.result()
    gc_task.result()
    for cq_code in ("locked-save", "locked-insert"):
        found = await repo.find_by_cq_code(cq_code)
        assert found is not None
        assert found.blob_data == content
    hash_only = await repo.find_by_cq_code("locked-hash-only")
    assert hash_only is not None
    assert hash_only.content_hash == content_hash
    assert hash_only.blob_path is None
    assert hash_only.blob_data is None
    hash_only_insert = await repo.find_by_cq_code("locked-hash-only-insert")
    assert hash_only_insert is not None
    assert hash_only_insert.content_hash == content_hash
    assert hash_only_insert.blob_path is None
    assert hash_only_insert.blob_data is None
    assert blob_store.read_image_blob(content_hash) == content


@pytest.mark.asyncio
async def test_image_cache_prune_commits_row_delete_before_waiting_for_blob_lock(pg_engine, tmp_path, monkeypatch):
    import hashlib

    from sqlalchemy import text

    from pallas.core.foundation.db import blob_store, repository_pg
    from pallas.core.foundation.db.modules import ImageCache
    from pallas.core.foundation.db.repository import ImageCachePrunePolicy
    from pallas.core.foundation.db.repository_pg import PgImageCacheRepository

    _isolate_image_blob_files(tmp_path, monkeypatch)
    content = b"pruned image blob"
    content_hash = hashlib.sha256(content).hexdigest()
    repo = PgImageCacheRepository()
    await repo.save(
        ImageCache.model_construct(
            cq_code="locked-prune", content_hash=content_hash, blob_data=content, ref_times=1, date=20260101
        )
    )
    prune_task = None

    async with repository_pg.get_session() as holder:
        await holder.execute(
            text("SELECT pg_advisory_xact_lock(:namespace, :key)"),
            {"namespace": 0x50414C4C, "key": _image_blob_lock_key(content_hash)},
        )
        prune_task = asyncio.create_task(
            repo.prune(
                ImageCachePrunePolicy(
                    single_use_before=20260801,
                    absolute_before=20260801,
                    max_blob_bytes=1000,
                    batch_size=10,
                )
            )
        )
        try:
            await _wait_for_image_blob_lock_waiters(pg_engine, content_hash, 1, tasks=(prune_task,))
            assert not prune_task.done()
            assert await repo.find_by_cq_code("locked-prune") is None
        finally:
            await holder.commit()
            await asyncio.wait_for(asyncio.gather(prune_task, return_exceptions=True), timeout=5)

    assert prune_task.result().deleted_rows == 1
    assert blob_store.read_image_blob(content_hash) is None


@pytest.mark.asyncio
async def test_image_cache_cleanup_and_gc_keep_canonical_path_with_mismatched_hash(pg_engine, tmp_path, monkeypatch):
    import hashlib

    from pallas.core.foundation.db import blob_store, repository_pg
    from pallas.core.foundation.db.lifecycle_adapters import PostgresLifecycleAdapter
    from pallas.core.foundation.db.repository_pg import image_cache_cleanup_blobs
    from pallas.core.foundation.db.repository_pg.schema import ImageCacheRow

    _isolate_image_blob_files(tmp_path, monkeypatch)
    content = b"historically mismatched metadata"
    content_hash = hashlib.sha256(content).hexdigest()
    rel_path = str(blob_store.image_blob_rel_path(content_hash))
    blob_store.write_image_blob(content_hash, content)
    async with repository_pg.get_session() as session:
        session.add(
            ImageCacheRow(
                cq_code="mismatched-path-reference",
                content_hash="b" * 64,
                blob_data=None,
                blob_path=rel_path,
                blob_size=len(content),
                ref_times=1,
                date=20261103,
            )
        )
        await session.commit()

    await image_cache_cleanup_blobs([content_hash])
    assert blob_store.read_image_blob(content_hash) == content
    assert await PostgresLifecycleAdapter().prune_image_cache_files() == (0, 0)
    assert blob_store.read_image_blob(content_hash) == content


@pytest.mark.asyncio
async def test_image_cache_bytea_migration_uses_actual_hash_and_pg_hash_lock(pg_engine, tmp_path, monkeypatch):
    import hashlib

    from sqlalchemy import select, text

    from pallas.core.foundation.db import blob_store, repository_pg
    from pallas.core.foundation.db.blob_store import image_blob_abs_path, image_blob_rel_path
    from pallas.core.foundation.db.image_cache_migration import migrate_image_cache_blobs
    from pallas.core.foundation.db.repository_pg.schema import ImageCacheRow

    _isolate_image_blob_files(tmp_path, monkeypatch)
    content = b"legacy bytea image"
    content_hash = hashlib.sha256(content).hexdigest()
    legacy_hash = "c" * 64
    existing_claimed_blob = b"preserve the file at the inconsistent hash"
    blob_store.write_image_blob(legacy_hash, existing_claimed_blob)
    async with repository_pg.get_session() as session:
        session.add(
            ImageCacheRow(
                cq_code="legacy-bytea",
                content_hash=legacy_hash,
                blob_data=content,
                blob_path=None,
                blob_size=None,
                ref_times=1,
                date=20261103,
            )
        )
        await session.commit()

    migration_task = None
    async with repository_pg.get_session() as holder:
        await holder.execute(
            text("SELECT pg_advisory_xact_lock(:namespace, :key)"),
            {"namespace": 0x50414C4C, "key": _image_blob_lock_key(content_hash)},
        )
        migration_task = asyncio.create_task(migrate_image_cache_blobs())
        try:
            waiter_pids = await _wait_for_image_blob_lock_waiters(pg_engine, content_hash, 1, tasks=(migration_task,))
            assert not migration_task.done()
            assert image_blob_abs_path(content_hash).exists() is False
            assert waiter_pids
        finally:
            await holder.commit()
            await asyncio.wait_for(asyncio.gather(migration_task, return_exceptions=True), timeout=5)

    assert migration_task.result() == 1
    async with repository_pg.get_session(read_only=True) as session:
        row = (await session.execute(select(ImageCacheRow).where(ImageCacheRow.cq_code == "legacy-bytea"))).scalar_one()
    assert row.content_hash == legacy_hash
    assert row.blob_path == str(image_blob_rel_path(content_hash))
    assert image_blob_abs_path(content_hash).read_bytes() == content
    assert image_blob_abs_path(legacy_hash).read_bytes() == existing_claimed_blob


@pytest.mark.asyncio
async def test_image_cache_migration_preserves_conflicting_actual_hash_blob(pg_engine, tmp_path, monkeypatch):
    import hashlib

    from sqlalchemy import select

    from pallas.core.foundation.db import blob_store, repository_pg
    from pallas.core.foundation.db.image_cache_migration import migrate_image_cache_blobs
    from pallas.core.foundation.db.repository_pg.schema import ImageCacheRow

    _isolate_image_blob_files(tmp_path, monkeypatch)
    content = b"migration payload A"
    content_hash = hashlib.sha256(content).hexdigest()
    legacy_hash = "c" * 64
    conflicting_blob = b"historical wrong-content file B"
    blob_store.write_image_blob(content_hash, conflicting_blob)
    async with repository_pg.get_session() as session:
        session.add(
            ImageCacheRow(
                cq_code="migration-hash-conflict",
                content_hash=legacy_hash,
                blob_data=content,
                blob_path=None,
                blob_size=len(content),
                ref_times=1,
                date=20261103,
            )
        )
        await session.commit()

    with pytest.raises(ValueError, match="existing image blob content does not match"):
        await migrate_image_cache_blobs()

    assert blob_store.read_image_blob(content_hash) == conflicting_blob
    async with repository_pg.get_session(read_only=True) as session:
        row = (
            await session.execute(select(ImageCacheRow).where(ImageCacheRow.cq_code == "migration-hash-conflict"))
        ).scalar_one()
    assert row.content_hash == legacy_hash
    assert row.blob_data == content
    assert row.blob_path is None


@pytest.mark.asyncio
async def test_image_cache_migration_releases_each_hash_lock_and_row_before_next(pg_engine, tmp_path, monkeypatch):
    import hashlib

    from sqlalchemy import text

    from pallas.core.foundation.db import blob_store, repository_pg
    from pallas.core.foundation.db.image_cache_migration import migrate_image_cache_blobs
    from pallas.core.foundation.db.repository_pg.schema import ImageCacheRow

    _isolate_image_blob_files(tmp_path, monkeypatch)
    first_data = b"first legacy bytea"
    second_data = b"second legacy bytea"
    second_hash = hashlib.sha256(second_data).hexdigest()
    async with repository_pg.get_session() as session:
        first = ImageCacheRow(
            cq_code="migration-first",
            content_hash=None,
            blob_data=first_data,
            blob_path=None,
            blob_size=None,
            ref_times=1,
            date=20261103,
        )
        session.add_all([
            first,
            ImageCacheRow(
                cq_code="migration-second",
                content_hash=None,
                blob_data=second_data,
                blob_path=None,
                blob_size=None,
                ref_times=1,
                date=20261103,
            ),
        ])
        await session.flush()
        first_id = first.id
        await session.commit()

    migration_task = None
    async with repository_pg.get_session() as holder:
        await holder.execute(
            text("SELECT pg_advisory_xact_lock(:namespace, :key)"),
            {"namespace": 0x50414C4C, "key": _image_blob_lock_key(second_hash)},
        )
        migration_task = asyncio.create_task(migrate_image_cache_blobs())
        try:
            await _wait_for_image_blob_lock_waiters(pg_engine, second_hash, 1, tasks=(migration_task,))
            assert not migration_task.done()
            async with repository_pg.get_session() as row_probe:
                await row_probe.execute(
                    text("SELECT id FROM image_cache WHERE id = :id FOR UPDATE NOWAIT"), {"id": first_id}
                )
                await row_probe.commit()
        finally:
            await holder.commit()
            await asyncio.wait_for(asyncio.gather(migration_task, return_exceptions=True), timeout=5)

    assert migration_task.result() == 2
    assert blob_store.read_image_blob(hashlib.sha256(first_data).hexdigest()) == first_data
    assert blob_store.read_image_blob(second_hash) == second_data


@pytest.mark.asyncio
async def test_image_cache_bind_content_hash_locks_hash_before_row_and_validates_file(pg_engine, tmp_path, monkeypatch):
    import hashlib

    from sqlalchemy import select, text

    from pallas.core.foundation.db import blob_store, repository_pg
    from pallas.core.foundation.db.repository_pg import PgImageCacheRepository
    from pallas.core.foundation.db.repository_pg.schema import ImageCacheRow

    _isolate_image_blob_files(tmp_path, monkeypatch)
    content = b"bind file-backed image"
    content_hash = hashlib.sha256(content).hexdigest()
    old_hash = "d" * 64
    blob_store.write_image_blob(content_hash, content)
    async with repository_pg.get_session() as session:
        row = ImageCacheRow(
            cq_code="bind-file",
            content_hash=old_hash,
            blob_data=None,
            blob_path=str(blob_store.image_blob_rel_path(content_hash)),
            blob_size=len(content),
            ref_times=1,
            date=20261103,
        )
        session.add(row)
        await session.flush()
        row_id = row.id
        await session.commit()

    repo = PgImageCacheRepository()
    bind_task = None
    probe_task = None
    async with repository_pg.get_session() as row_holder:
        await row_holder.execute(select(ImageCacheRow.id).where(ImageCacheRow.id == row_id).with_for_update())
        bind_task = asyncio.create_task(repo.bind_content_hash("bind-file", content_hash))
        try:
            await _wait_for_image_cache_row_lock_waiter(pg_engine, tasks=(bind_task,))

            async def lock_probe():
                async with repository_pg.get_session() as session:
                    await session.connection(execution_options={"isolation_level": "READ COMMITTED"})
                    await session.execute(
                        text("SELECT pg_advisory_xact_lock(:namespace, :key)"),
                        {"namespace": 0x50414C4C, "key": _image_blob_lock_key(content_hash)},
                    )
                    await session.commit()

            probe_task = asyncio.create_task(lock_probe())
            await _wait_for_image_blob_lock_waiters(pg_engine, content_hash, 1, tasks=(bind_task, probe_task))
            assert not bind_task.done()
            assert not probe_task.done()
        finally:
            await row_holder.commit()
            await asyncio.wait_for(asyncio.gather(bind_task, probe_task, return_exceptions=True), timeout=5)

    bind_task.result()
    probe_task.result()
    with pytest.raises(ValueError, match="content_hash"):
        await repo.bind_content_hash("bind-file", "e" * 64)
    await repo.bind_content_hash("missing-bind-row", content_hash)
    bound = await repo.find_by_cq_code("bind-file")
    assert bound is not None
    assert bound.content_hash == content_hash
    assert bound.blob_data == content


@pytest.mark.asyncio
async def test_image_cache_bind_content_hash_validates_bytea_before_update(pg_engine):
    import hashlib

    from pallas.core.foundation.db import repository_pg
    from pallas.core.foundation.db.repository_pg import PgImageCacheRepository
    from pallas.core.foundation.db.repository_pg.schema import ImageCacheRow

    content = b"bind bytea image"
    content_hash = hashlib.sha256(content).hexdigest()
    async with repository_pg.get_session() as session:
        session.add(
            ImageCacheRow(
                cq_code="bind-bytea",
                content_hash="a" * 64,
                blob_data=content,
                blob_path=None,
                blob_size=len(content),
                ref_times=1,
                date=20261103,
            )
        )
        await session.commit()

    repo = PgImageCacheRepository()
    await repo.bind_content_hash("bind-bytea", content_hash)
    with pytest.raises(ValueError, match="content_hash"):
        await repo.bind_content_hash("bind-bytea", "b" * 64)
    bound = await repo.find_by_cq_code("bind-bytea")
    assert bound is not None
    assert bound.content_hash == content_hash
    assert bound.blob_data == content


@pytest.mark.asyncio
async def test_image_cache_save_rejects_blob_hash_mismatch_without_overwrite(pg_engine, tmp_path, monkeypatch):
    from pallas.core.foundation.db import blob_store
    from pallas.core.foundation.db.modules import ImageCache
    from pallas.core.foundation.db.repository_pg import PgImageCacheRepository

    _isolate_image_blob_files(tmp_path, monkeypatch)
    wrong_hash = "f" * 64
    original = b"existing blob at a mislabelled key"
    blob_store.write_image_blob(wrong_hash, original)
    repo = PgImageCacheRepository()
    cache = ImageCache.model_construct(
        cq_code="hash-mismatch",
        content_hash=wrong_hash,
        blob_data=b"different payload",
        ref_times=1,
        date=20261103,
    )

    with pytest.raises(ValueError, match="content_hash"):
        await repo.save(cache)

    assert blob_store.read_image_blob(wrong_hash) == original
    assert await repo.find_by_cq_code("hash-mismatch") is None


@pytest.mark.asyncio
async def test_image_cache_save_replaces_legacy_bytea_with_new_file_blob(pg_engine, tmp_path, monkeypatch):
    import hashlib

    from sqlalchemy import select

    from pallas.core.foundation.db import blob_store, repository_pg
    from pallas.core.foundation.db.modules import ImageCache
    from pallas.core.foundation.db.repository_pg import PgImageCacheRepository
    from pallas.core.foundation.db.repository_pg.schema import ImageCacheRow

    _isolate_image_blob_files(tmp_path, monkeypatch)
    old_data = b"legacy bytea A"
    new_data = b"replacement blob B"
    new_hash = hashlib.sha256(new_data).hexdigest()
    async with repository_pg.get_session() as session:
        session.add(
            ImageCacheRow(
                cq_code="replace-legacy-bytea",
                content_hash=hashlib.sha256(old_data).hexdigest(),
                blob_data=old_data,
                blob_path=None,
                blob_size=len(old_data),
                ref_times=1,
                date=20261103,
            )
        )
        await session.commit()

    repo = PgImageCacheRepository()
    await repo.save(
        ImageCache.model_construct(
            cq_code="replace-legacy-bytea",
            content_hash=new_hash,
            blob_data=new_data,
            ref_times=2,
            date=20261104,
        )
    )
    found = await repo.find_by_cq_code("replace-legacy-bytea")
    assert found is not None
    assert found.blob_data == new_data
    assert found.content_hash == new_hash
    assert blob_store.read_image_blob(new_hash) == new_data

    await repo.save(found)
    async with repository_pg.get_session(read_only=True) as session:
        row = (
            await session.execute(select(ImageCacheRow).where(ImageCacheRow.cq_code == "replace-legacy-bytea"))
        ).scalar_one()
    assert row.blob_data is None
    assert row.content_hash == new_hash
    assert row.blob_path == str(blob_store.image_blob_rel_path(new_hash))
    assert blob_store.read_image_blob(new_hash) == new_data


@pytest.mark.asyncio
async def test_image_cache_save_preserves_verified_migration_alias_without_overwriting_alias_file(
    pg_engine, tmp_path, monkeypatch
):
    import hashlib

    from sqlalchemy import select

    from pallas.core.foundation.db import blob_store, repository_pg
    from pallas.core.foundation.db.image_cache_migration import migrate_image_cache_blobs
    from pallas.core.foundation.db.repository_pg import PgImageCacheRepository
    from pallas.core.foundation.db.repository_pg.schema import ImageCacheRow

    _isolate_image_blob_files(tmp_path, monkeypatch)
    data = b"content behind a historical alias"
    actual_hash = hashlib.sha256(data).hexdigest()
    alias = "f" * 64
    assert alias != actual_hash
    alias_file = b"another row's shared file at the alias path"
    blob_store.write_image_blob(alias, alias_file)
    async with repository_pg.get_session() as session:
        session.add_all([
            ImageCacheRow(
                cq_code="legacy-alias",
                content_hash=alias,
                blob_data=data,
                blob_path=None,
                blob_size=len(data),
                ref_times=1,
                date=20261103,
            ),
            ImageCacheRow(
                cq_code="other-alias-path-reference",
                content_hash="e" * 64,
                blob_data=None,
                blob_path=str(blob_store.image_blob_rel_path(alias)),
                blob_size=len(alias_file),
                ref_times=1,
                date=20261103,
            ),
        ])
        await session.commit()

    assert await migrate_image_cache_blobs() == 1
    repo = PgImageCacheRepository()
    found = await repo.find_by_cq_code("legacy-alias")
    assert found is not None
    assert found.content_hash == alias
    assert found.blob_data == data
    await repo.save(found)

    found_again = await repo.find_by_cq_code("legacy-alias")
    assert found_again is not None
    assert found_again.content_hash == alias
    assert found_again.blob_data == data
    await repo.save(found_again)

    async with repository_pg.get_session(read_only=True) as session:
        row = (await session.execute(select(ImageCacheRow).where(ImageCacheRow.cq_code == "legacy-alias"))).scalar_one()
    assert row.content_hash == alias
    assert row.blob_path == str(blob_store.image_blob_rel_path(actual_hash))
    assert row.blob_data is None
    assert blob_store.read_image_blob(actual_hash) == data
    assert blob_store.read_image_blob(alias) == alias_file


@pytest.mark.parametrize("trusted_alias", [False, True], ids=["canonical-hash", "legacy-alias"])
@pytest.mark.asyncio
async def test_image_cache_save_preserves_conflicting_actual_hash_blob(pg_engine, tmp_path, monkeypatch, trusted_alias):
    import hashlib

    from sqlalchemy import select

    from pallas.core.foundation.db import blob_store, repository_pg
    from pallas.core.foundation.db.modules import ImageCache
    from pallas.core.foundation.db.repository_pg import PgImageCacheRepository
    from pallas.core.foundation.db.repository_pg.schema import ImageCacheRow

    _isolate_image_blob_files(tmp_path, monkeypatch)
    content = b"save payload A"
    actual_hash = hashlib.sha256(content).hexdigest()
    stored_hash = "d" * 64 if trusted_alias else actual_hash
    if trusted_alias:
        assert stored_hash != actual_hash
    else:
        assert stored_hash == actual_hash
    conflicting_blob = b"historical wrong-content file B"
    blob_store.write_image_blob(actual_hash, conflicting_blob)
    if trusted_alias:
        async with repository_pg.get_session() as session:
            session.add(
                ImageCacheRow(
                    cq_code="save-hash-conflict",
                    content_hash=stored_hash,
                    blob_data=content,
                    blob_path=None,
                    blob_size=len(content),
                    ref_times=1,
                    date=20261103,
                )
            )
            await session.commit()

    repo = PgImageCacheRepository()
    with pytest.raises(ValueError, match="existing image blob content does not match"):
        await repo.save(
            ImageCache.model_construct(
                cq_code="save-hash-conflict",
                content_hash=stored_hash,
                blob_data=content,
                ref_times=2,
                date=20261104,
            )
        )

    assert blob_store.read_image_blob(actual_hash) == conflicting_blob
    async with repository_pg.get_session(read_only=True) as session:
        result = await session.execute(select(ImageCacheRow).where(ImageCacheRow.cq_code == "save-hash-conflict"))
        row = result.scalar_one_or_none()
    if trusted_alias:
        assert row is not None
        assert row.content_hash == stored_hash
        assert row.blob_data == content
        assert row.blob_path is None
    else:
        assert row is None


@pytest.mark.asyncio
async def test_image_cache_save_rejects_forged_historical_alias_payload(pg_engine, tmp_path, monkeypatch):
    import hashlib

    from sqlalchemy import select

    from pallas.core.foundation.db import blob_store, repository_pg
    from pallas.core.foundation.db.modules import ImageCache
    from pallas.core.foundation.db.repository_pg import PgImageCacheRepository
    from pallas.core.foundation.db.repository_pg.schema import ImageCacheRow

    _isolate_image_blob_files(tmp_path, monkeypatch)
    alias = "f" * 64
    original = b"row's original payload"
    forged = b"different caller-supplied payload"
    alias_file = b"shared file not to overwrite"
    blob_store.write_image_blob(alias, alias_file)
    async with repository_pg.get_session() as session:
        session.add(
            ImageCacheRow(
                cq_code="forged-alias",
                content_hash=alias,
                blob_data=original,
                blob_path=None,
                blob_size=len(original),
                ref_times=1,
                date=20261103,
            )
        )
        await session.commit()

    repo = PgImageCacheRepository()
    with pytest.raises(ValueError, match="content_hash"):
        await repo.save(
            ImageCache.model_construct(
                cq_code="forged-alias",
                content_hash=alias,
                blob_data=forged,
                ref_times=1,
                date=20261104,
            )
        )

    async with repository_pg.get_session(read_only=True) as session:
        row = (await session.execute(select(ImageCacheRow).where(ImageCacheRow.cq_code == "forged-alias"))).scalar_one()
    assert row.blob_data == original
    assert row.content_hash == alias
    assert blob_store.read_image_blob(alias) == alias_file
    assert blob_store.read_image_blob(hashlib.sha256(forged).hexdigest()) is None


@pytest.mark.asyncio
async def test_image_cache_clear_blob_verifies_file_under_hash_then_row_lock(pg_engine, tmp_path, monkeypatch):
    import hashlib

    from sqlalchemy import select, text

    from pallas.core.foundation.db import blob_store, repository_pg
    from pallas.core.foundation.db.image_cache_migration import migrate_image_cache_blobs
    from pallas.core.foundation.db.repository_pg.schema import ImageCacheRow

    _isolate_image_blob_files(tmp_path, monkeypatch)
    good_data = b"bytea with matching file"
    bad_data = b"bytea whose file disagrees"
    missing_data = b"bytea whose file is missing"
    good_hash = hashlib.sha256(good_data).hexdigest()
    bad_hash = hashlib.sha256(bad_data).hexdigest()
    missing_hash = hashlib.sha256(missing_data).hexdigest()
    symlink_data = b"bytea whose verified copy is a symlink"
    symlink_hash = hashlib.sha256(symlink_data).hexdigest()
    symlink_target_hash = "e" * 64
    assert symlink_hash != symlink_target_hash
    blob_store.write_image_blob(good_hash, good_data)
    blob_store.write_image_blob(bad_hash, b"different bytes")
    blob_store.write_image_blob(symlink_target_hash, symlink_data)
    symlink_path = blob_store.image_blob_abs_path(symlink_hash)
    symlink_path.parent.mkdir(parents=True)
    symlink_path.symlink_to(blob_store.image_blob_abs_path(symlink_target_hash))
    assert blob_store.read_image_blob_at(str(blob_store.image_blob_rel_path(symlink_hash))) == symlink_data
    async with repository_pg.get_session() as session:
        rows = [
            ImageCacheRow(
                cq_code="clear-good",
                content_hash="a" * 64,
                blob_data=good_data,
                blob_path=str(blob_store.image_blob_rel_path(good_hash)),
                blob_size=len(good_data),
                ref_times=1,
                date=20261103,
            ),
            ImageCacheRow(
                cq_code="clear-mismatch",
                content_hash="b" * 64,
                blob_data=bad_data,
                blob_path=str(blob_store.image_blob_rel_path(bad_hash)),
                blob_size=len(bad_data),
                ref_times=1,
                date=20261103,
            ),
            ImageCacheRow(
                cq_code="clear-missing",
                content_hash="c" * 64,
                blob_data=missing_data,
                blob_path=str(blob_store.image_blob_rel_path(missing_hash)),
                blob_size=len(missing_data),
                ref_times=1,
                date=20261103,
            ),
            ImageCacheRow(
                cq_code="clear-symlink",
                content_hash="d" * 64,
                blob_data=symlink_data,
                blob_path=str(blob_store.image_blob_rel_path(symlink_hash)),
                blob_size=len(symlink_data),
                ref_times=1,
                date=20261103,
            ),
        ]
        session.add_all(rows)
        await session.flush()
        good_id = rows[0].id
        await session.commit()

    async with repository_pg.get_session(read_only=True) as session:
        symlink_row = (
            await session.execute(select(ImageCacheRow).where(ImageCacheRow.cq_code == "clear-symlink"))
        ).scalar_one()
    assert symlink_row.blob_data == symlink_data

    clear_task = None
    lock_probe = None
    async with repository_pg.get_session() as row_holder:
        await row_holder.execute(select(ImageCacheRow.id).where(ImageCacheRow.id == good_id).with_for_update())
        clear_task = asyncio.create_task(migrate_image_cache_blobs(clear_blob=True))
        try:
            await _wait_for_image_cache_row_lock_waiter(pg_engine, tasks=(clear_task,))

            async def acquire_good_hash_lock():
                async with repository_pg.get_session() as session:
                    await session.connection(execution_options={"isolation_level": "READ COMMITTED"})
                    await session.execute(
                        text("SELECT pg_advisory_xact_lock(:namespace, :key)"),
                        {"namespace": 0x50414C4C, "key": _image_blob_lock_key(good_hash)},
                    )
                    await session.commit()

            lock_probe = asyncio.create_task(acquire_good_hash_lock())
            await _wait_for_image_blob_lock_waiters(pg_engine, good_hash, 1, tasks=(lock_probe,))
            assert not clear_task.done()
            assert not lock_probe.done()
        finally:
            await row_holder.commit()
            await asyncio.wait_for(asyncio.gather(clear_task, lock_probe, return_exceptions=True), timeout=5)

    clear_task.result()
    lock_probe.result()
    async with repository_pg.get_session(read_only=True) as session:
        rows = (
            (
                await session.execute(
                    select(ImageCacheRow).where(
                        ImageCacheRow.cq_code.in_(["clear-good", "clear-mismatch", "clear-missing", "clear-symlink"])
                    )
                )
            )
            .scalars()
            .all()
        )
    found = {row.cq_code: row for row in rows}
    assert found["clear-good"].blob_data is None
    assert found["clear-mismatch"].blob_data == bad_data
    assert found["clear-missing"].blob_data == missing_data
    assert found["clear-symlink"].blob_data == symlink_data
    assert symlink_path.is_symlink()
    assert blob_store.read_image_blob(symlink_target_hash) == symlink_data


@pytest.mark.asyncio
async def test_config_cache_hit_and_invalidate_on_write(pg_engine):
    """读后走 TTL 缓存；一旦 upsert_field 写入必须让缓存失效，下次读能拿到新值。"""
    from pallas.core.foundation.db.repository_pg import PgConfigRepository

    repo = PgConfigRepository("bot_config", "account")
    await repo.upsert_field(1001, "security", True)
    row1 = await repo.get(1001)
    assert row1 is not None
    assert row1.security is True

    await repo.upsert_field(1001, "security", False)
    row2 = await repo.get(1001)
    assert row2 is not None
    assert row2.security is False


@pytest.mark.asyncio
async def test_config_list_all_returns_detached_rows(pg_engine):
    from pallas.core.foundation.db.repository_pg import PgConfigRepository

    repo = PgConfigRepository("bot_config", "account")
    await repo.upsert_field(4101, "disabled_plugins", ["a"])
    await repo.upsert_field(4102, "disabled_plugins", ["b"])

    rows = await repo.list_all()
    assert {int(row.account) for row in rows} >= {4101, 4102}


@pytest.mark.asyncio
async def test_config_cache_ignore_cache_forces_db_read(pg_engine):
    """ignore_cache=True 必须绕过缓存直接回源，不受外部 SQL 旁路改库影响。"""
    from sqlalchemy import update

    from pallas.core.foundation.db.repository_pg import BotConfigRow, PgConfigRepository, get_session

    repo = PgConfigRepository("bot_config", "account")
    await repo.upsert_field(2002, "security", True)
    assert (await repo.get(2002)).security is True

    # 绕过 repo 直接 SQL 改库
    async with get_session() as session:
        await session.execute(update(BotConfigRow).where(BotConfigRow.account == 2002).values(security=False))
        await session.commit()

    cached = await repo.get(2002)
    assert cached.security is True  # 走缓存：旧值
    fresh = await repo.get(2002, ignore_cache=True)
    assert fresh.security is False  # 回源：新值


@pytest.mark.asyncio
async def test_config_invalidate_all(pg_engine):
    """invalidate_cache() 必须能全量清空该 row_class 的缓存条目。"""
    from pallas.core.foundation.db.repository_pg import PgConfigRepository

    repo = PgConfigRepository("bot_config", "account")
    await repo.upsert_field(3003, "security", True)
    assert (await repo.get(3003)).security is True
    await repo.invalidate_cache()
    assert (await repo.get(3003)).security is True  # 数据未变，只是不再走缓存


@pytest.mark.asyncio
async def test_config_get_or_create_concurrent(pg_engine):
    """并发 get_or_create 同一 key 必须只有一次 created=True，不得出现 IntegrityError 冒泡。"""
    from pallas.core.foundation.db.repository_pg import PgConfigRepository

    repo = PgConfigRepository("bot_config", "account")
    key = int(uuid.uuid4().int & 0x7FFFFFFF)

    results = await asyncio.gather(*[repo.get_or_create(key, disabled_plugins=[]) for _ in range(20)])
    created_count = sum(1 for _, created in results if created)
    assert created_count <= 1
    row = await repo.get(key, ignore_cache=True)
    assert row is not None
