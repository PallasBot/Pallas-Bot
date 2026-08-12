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
async def test_find_by_keywords_for_reply_uses_one_read_round_trip(pg_engine):
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
    assert len(statements) == 1


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
    assert row.sender_name == "兔兔"
    assert row.message_id == 101
    assert row.reply_to_message_id == 90
    assert [m.plain_text for m in rows] == ["a", "b"]
    one = await repo.find_recent_in_group(gid, before_time=250, user_id=20, limit=1)
    assert len(one) == 1
    assert one[0].plain_text == "b"


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
    assert result.deleted_blob_bytes == 15
    assert result.remaining_blob_bytes == 10
    assert await repo.find_by_cq_code("absolute-old") is None
    assert await repo.find_by_cq_code("single-old") is None
    assert await repo.find_by_cq_code("single-new") is None
    assert await repo.find_by_cq_code("popular-oldest") is not None
    assert await repo.find_by_cq_code("popular-newest") is not None


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
