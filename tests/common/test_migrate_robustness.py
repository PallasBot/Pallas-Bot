"""
Mongo → PG 迁移脚本健壮性测试。

依赖：本地 PG 实例（通过 `PG_TEST_DSN` 注入）。未设置则 skip。
Mongo 侧用最小 fake 对象代替，不需要真实 Mongo。
"""

from __future__ import annotations

import importlib.util
import os
import sys
import uuid
from pathlib import Path
from typing import Any

import pytest

_DSN = os.getenv("PG_TEST_DSN")

pytestmark = pytest.mark.skipif(not _DSN, reason="需要设置 PG_TEST_DSN 指向测试 PG 实例")


_ROOT = Path(__file__).resolve().parents[2]


def _load_migrate_module():
    """动态加载 tools/migrate_mongo_to_pg.py（它不是 package）。"""
    mod_name = "_pallas_migrate_mongo_to_pg"
    if mod_name in sys.modules:
        return sys.modules[mod_name]
    spec = importlib.util.spec_from_file_location(mod_name, _ROOT / "tools" / "migrate_mongo_to_pg.py")
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[mod_name] = mod
    spec.loader.exec_module(mod)
    return mod


# ---------------------------------------------------------------------------
# Fake Mongo 最小实现
# ---------------------------------------------------------------------------


class _FakeCursor:
    def __init__(self, docs: list[dict]) -> None:
        self._docs = docs
        self._sort_key: str | None = None
        self._limit: int | None = None

    def sort(self, key: str, direction: int = 1) -> "_FakeCursor":
        self._sort_key = key
        reverse = direction < 0
        self._docs = sorted(self._docs, key=lambda d: d.get(key), reverse=reverse)
        return self

    def limit(self, n: int) -> "_FakeCursor":
        self._limit = n
        return self

    async def to_list(self, length: int | None = None):
        out = self._docs
        if self._limit is not None:
            out = out[: self._limit]
        if length is not None:
            out = out[:length]
        return list(out)


class _FakeCollection:
    def __init__(self, docs: list[dict] | None = None) -> None:
        self._docs = docs or []

    async def count_documents(self, q: dict) -> int:
        return sum(1 for d in self._docs if self._match(d, q))

    def find(self, q: dict | None = None):
        q = q or {}
        return _FakeCursor([d for d in self._docs if self._match(d, q)])

    @staticmethod
    def _match(doc: dict, q: dict) -> bool:
        for k, v in q.items():
            if isinstance(v, dict) and "$gt" in v:
                if not (doc.get(k) is not None and doc.get(k) > v["$gt"]):
                    return False
            elif doc.get(k) != v:
                return False
        return True


class _FakeDb:
    def __init__(self, collections: dict[str, list[dict]]) -> None:
        self._cols = {name: _FakeCollection(list(docs)) for name, docs in collections.items()}

    def __getitem__(self, name: str) -> _FakeCollection:
        return self._cols.setdefault(name, _FakeCollection([]))


# ---------------------------------------------------------------------------
# PG engine fixture（与 test_repository_pg 共用模式）
# ---------------------------------------------------------------------------


@pytest.fixture
async def pg_env():
    from sqlalchemy.dialects.postgresql import insert as pg_insert
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from src.common.db.repository_pg import Base, dispose_pg, init_pg

    assert _DSN is not None
    engine = create_async_engine(_DSN)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await init_pg(engine)

    migrate = _load_migrate_module()
    # 建好 migration_state 表
    await migrate._ensure_state_table(engine)

    sf = async_sessionmaker(engine, expire_on_commit=False)
    try:
        yield {
            "engine": engine,
            "sf": sf,
            "migrate": migrate,
            "pg_insert": pg_insert,
        }
    finally:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
        await dispose_pg()


# ---------------------------------------------------------------------------
# Defensive helpers 单元测试
# ---------------------------------------------------------------------------


def test_defensive_helpers_handle_garbage():
    m = _load_migrate_module()
    assert m._as_int("5") == 5
    assert m._as_int("abc", 99) == 99
    assert m._as_int(None, 7) == 7
    assert m._as_int(True) == 1
    assert m._as_bool("true") is True
    assert m._as_bool("0") is False
    assert m._as_bool(None, True) is True
    assert m._as_list(None) == []
    assert m._as_list((1, 2)) == [1, 2]
    assert m._as_list("nope") == []
    assert m._as_dict(None) == {}
    assert m._as_dict([1]) == {}
    assert m._strip_null("a\x00b") == "ab"
    assert m._strip_null({"k": "v\x00"}) == {"k": "v"}
    assert m._strip_null(["x\x00", {"y": "z\x00"}]) == ["x", {"y": "z"}]


# ---------------------------------------------------------------------------
# Context 迁移：脏数据 + keywords 合并 + \x00
# ---------------------------------------------------------------------------


async def test_migrate_context_merges_duplicate_keywords(pg_env):
    from bson import ObjectId

    from src.common.db.repository_pg import ContextAnswerMessageRow, ContextAnswerRow, ContextBanRow, ContextRow

    migrate = pg_env["migrate"]
    # 同 keywords 在 Mongo 中出现两条（脏数据场景）
    docs = [
        {
            "_id": ObjectId(),
            "keywords": "dup\x00kw",
            "time": 100,
            "trigger_count": 3,
            "clear_time": 0,
            "answers": [
                {"keywords": "a", "group_id": 1, "count": 2, "time": 100, "messages": ["m1", "m2\x00"]},
            ],
            "ban": [{"keywords": "b", "group_id": 1, "reason": "r1\x00", "time": 100}],
        },
        {
            "_id": ObjectId(),
            "keywords": "dup\x00kw",  # 同 keywords
            "time": 200,
            "trigger_count": 1,
            "clear_time": 50,
            "answers": [
                {"keywords": "a", "group_id": 1, "count": 1, "time": 200, "messages": ["m3"]},  # 同 answer key
                {"keywords": "c", "group_id": 2, "count": 1, "time": 200, "messages": []},
            ],
            "ban": [],
        },
        # 脏数据：空 keywords 应被 skip
        {"_id": ObjectId(), "keywords": "", "time": 0, "answers": [], "ban": []},
        # 脏数据：answers 里混入非 dict，应被忽略
        {"_id": ObjectId(), "keywords": "weird", "time": 0, "answers": ["not a dict", None], "ban": []},
    ]
    db = _FakeDb({"context": docs})

    await migrate._migrate_context(
        db,
        pg_env["sf"],
        ContextRow,
        ContextAnswerRow,
        ContextAnswerMessageRow,
        ContextBanRow,
        pg_env["pg_insert"],
        batch_size=100,
        dry_run=False,
    )

    from sqlalchemy import select

    async with pg_env["sf"]() as session:
        ctxs = (await session.execute(select(ContextRow))).scalars().all()
        # "dup...kw" 合并成一条 + "weird" 一条 = 2
        assert len(ctxs) == 2, [c.keywords for c in ctxs]
        dup = next(c for c in ctxs if "dup" in c.keywords)
        assert "\x00" not in dup.keywords
        # 合并后 time/trigger_count/clear_time 应该取 max
        assert dup.time == 200
        assert dup.trigger_count == 3
        assert dup.clear_time == 50

        ans = (await session.execute(select(ContextAnswerRow).where(ContextAnswerRow.context_id == dup.id))).scalars().all()
        # (group=1, kw=a) 合并, (group=2, kw=c) 单独 = 2
        assert len(ans) == 2
        ans_a = next(a for a in ans if a.group_id == 1 and a.keywords == "a")
        # count 累加
        assert ans_a.count == 3
        # time 取 max
        assert ans_a.time == 200

        msgs = (await session.execute(
            select(ContextAnswerMessageRow).where(ContextAnswerMessageRow.answer_id == ans_a.id)
        )).scalars().all()
        all_msgs = {m.message for m in msgs}
        assert all_msgs == {"m1", "m2", "m3"}
        assert all("\x00" not in m for m in all_msgs)

        bans = (await session.execute(select(ContextBanRow).where(ContextBanRow.context_id == dup.id))).scalars().all()
        assert len(bans) == 1
        assert "\x00" not in bans[0].reason


# ---------------------------------------------------------------------------
# Message 迁移 + 断点续传
# ---------------------------------------------------------------------------


async def test_migrate_message_resumable(pg_env):
    """模拟已迁移部分数据后重跑，只补齐未迁移的部分。"""
    from bson import ObjectId
    from sqlalchemy import func, select

    from src.common.db.repository_pg import MessageRow

    migrate = pg_env["migrate"]

    ids = [ObjectId() for _ in range(10)]
    docs = [
        {
            "_id": ids[i],
            "group_id": 1,
            "user_id": 2,
            "bot_id": 3,
            "raw_message": f"msg{i}\x00",
            "is_plain_text": True,
            "plain_text": f"msg{i}",
            "keywords": "",
            "time": 100 + i,
        }
        for i in range(10)
    ]
    db = _FakeDb({"message": docs})

    # 第一次：只迁前 5 条（人为写 state）
    async with pg_env["sf"]() as session:
        # 先迁前 5
        from sqlalchemy import insert as sa_insert

        for i in range(5):
            await session.execute(
                sa_insert(MessageRow).values(
                    group_id=1, user_id=2, bot_id=3,
                    raw_message=f"msg{i}", is_plain_text=True, plain_text=f"msg{i}",
                    keywords="", time=100 + i,
                )
            )
        await migrate._set_state(session, "message", str(ids[4]))
        await session.commit()

    # 第二次：从 state 续迁
    await migrate._migrate_message(
        db, pg_env["sf"], MessageRow, pg_env["pg_insert"], batch_size=100, dry_run=False
    )

    async with pg_env["sf"]() as session:
        total = (await session.execute(select(func.count()).select_from(MessageRow))).scalar_one()
        assert total == 10  # 前 5 + 后 5, 无重复
        # \x00 应被剥除
        rows = (await session.execute(select(MessageRow).order_by(MessageRow.time))).scalars().all()
        assert all("\x00" not in r.raw_message for r in rows)


async def test_migrate_message_dirty_rows_counted(pg_env):
    """脏数据（字段错类型）应 skip 并计入 failed，但不阻断。"""
    from bson import ObjectId
    from sqlalchemy import func, select

    from src.common.db.repository_pg import MessageRow

    migrate = pg_env["migrate"]

    docs = [
        # 正常
        {
            "_id": ObjectId(),
            "group_id": 1,
            "user_id": 2,
            "bot_id": 3,
            "raw_message": "ok",
            "is_plain_text": True,
            "plain_text": "ok",
            "keywords": "",
            "time": 100,
        },
        # 非法 group_id（字符串），defensive 转 0 还是能插入（保守处理）
        {
            "_id": ObjectId(),
            "group_id": "not-a-number",
            "user_id": 2,
            "bot_id": 3,
            "raw_message": "weird",
            "is_plain_text": True,
            "plain_text": "weird",
            "keywords": "",
            "time": 101,
        },
    ]
    db = _FakeDb({"message": docs})
    stats = await migrate._migrate_message(
        db, pg_env["sf"], MessageRow, pg_env["pg_insert"], batch_size=100, dry_run=False
    )
    # 两条都应成功（defensive 把字符串 group_id 转成 0）
    async with pg_env["sf"]() as session:
        total = (await session.execute(select(func.count()).select_from(MessageRow))).scalar_one()
    assert total == 2
    assert stats.failed == 0


# ---------------------------------------------------------------------------
# BlackList / Config 迁移
# ---------------------------------------------------------------------------


async def test_migrate_blacklist_rerun_idempotent(pg_env):
    from bson import ObjectId
    from sqlalchemy import func, select

    from src.common.db.repository_pg import BlackListRow

    migrate = pg_env["migrate"]
    docs = [
        {"_id": ObjectId(), "group_id": 1, "answers": ["a\x00", "b"], "answers_reserve": []},
        {"_id": ObjectId(), "group_id": 2, "answers": [], "answers_reserve": ["x"]},
    ]
    db = _FakeDb({"blacklist": docs})

    await migrate._migrate_blacklist(db, pg_env["sf"], BlackListRow, pg_env["pg_insert"], batch_size=100, dry_run=False)

    # 重跑：因 migration_state 记录的 last_id 已经是最后一条 _id，游标没有新数据
    await migrate._migrate_blacklist(db, pg_env["sf"], BlackListRow, pg_env["pg_insert"], batch_size=100, dry_run=False)

    async with pg_env["sf"]() as session:
        rows = (await session.execute(select(BlackListRow).order_by(BlackListRow.group_id))).scalars().all()
        assert len(rows) == 2
        assert rows[0].answers == ["a", "b"]
        assert rows[1].answers_reserve == ["x"]


async def test_migrate_bot_config_handles_auto_accept_legacy(pg_env):
    """旧 schema：auto_accept 仅存 group 维度；新 schema 拆成 friend/group。"""
    from bson import ObjectId
    from sqlalchemy import select

    from src.common.db.repository_pg import BotConfigRow

    migrate = pg_env["migrate"]
    docs = [
        # 旧字段
        {"_id": ObjectId(), "account": 1001, "auto_accept": True, "admins": [1, "2", "bad"], "taken_name": {"100": 1}, "drunk": {"200": 0.5}},
        # 新字段
        {"_id": ObjectId(), "account": 1002, "auto_accept_group": False, "auto_accept_friend": True},
    ]
    db = _FakeDb({"config": docs})

    await migrate._migrate_bot_config(db, pg_env["sf"], BotConfigRow, pg_env["pg_insert"], batch_size=100, dry_run=False)

    async with pg_env["sf"]() as session:
        rows = (await session.execute(select(BotConfigRow).order_by(BotConfigRow.account))).scalars().all()
        assert rows[0].account == 1001
        assert rows[0].auto_accept_group is True
        assert rows[0].auto_accept_friend is False
        assert rows[0].admins == [1, 2]  # "bad" 被 skip
        assert rows[1].auto_accept_group is False
        assert rows[1].auto_accept_friend is True


async def test_migrate_image_cache_upsert(pg_env):
    from bson import ObjectId
    from sqlalchemy import select

    from src.common.db.repository_pg import ImageCacheRow

    migrate = pg_env["migrate"]
    docs = [
        {"_id": ObjectId(), "cq_code": "[CQ:image,file=a.image]", "base64_data": None, "ref_times": 1, "date": 20250101},
        # 同 cq_code 再来一条，应 upsert 取最新
        {"_id": ObjectId(), "cq_code": "[CQ:image,file=a.image]", "base64_data": "b64", "ref_times": 5, "date": 20250110},
        # 脏：空 cq_code
        {"_id": ObjectId(), "cq_code": "", "base64_data": None, "ref_times": 1, "date": 20250101},
    ]
    db = _FakeDb({"image_cache": docs})

    stats = await migrate._migrate_image_cache(
        db, pg_env["sf"], ImageCacheRow, pg_env["pg_insert"], batch_size=100, dry_run=False
    )

    async with pg_env["sf"]() as session:
        rows = (await session.execute(select(ImageCacheRow))).scalars().all()
    assert len(rows) == 1
    assert rows[0].ref_times == 5
    assert rows[0].base64_data == "b64"
    assert stats.failed >= 1  # 空 cq_code 那条


# ---------------------------------------------------------------------------
# 游标流式工具
# ---------------------------------------------------------------------------


async def test_stream_batches_orders_by_id_and_paginates():
    migrate = _load_migrate_module()
    from bson import ObjectId

    # 构造 25 个按 id 递增的 doc
    ids = [ObjectId() for _ in range(25)]
    docs = [{"_id": ids[i], "n": i} for i in range(25)]
    col = _FakeCollection(docs)

    seen: list[int] = []
    async for batch in migrate._stream_batches(col, None, batch_size=10):
        seen.extend(d["n"] for d in batch)
    assert seen == list(range(25))

    # 从中间续传
    resume_from = str(ids[9])
    seen2: list[int] = []
    async for batch in migrate._stream_batches(col, resume_from, batch_size=10):
        seen2.extend(d["n"] for d in batch)
    assert seen2 == list(range(10, 25))


async def test_dedupe_answers_aggregates_correctly():
    migrate = _load_migrate_module()

    answers = [
        {"keywords": "a", "group_id": 1, "count": 3, "time": 100, "messages": ["m1"]},
        {"keywords": "a", "group_id": 1, "count": 2, "time": 200, "messages": ["m2", "m3"]},
        {"keywords": "b", "group_id": 1, "count": 1, "time": 150, "messages": ["m4"]},
    ]
    result = migrate._dedupe_answers(answers)
    result.sort(key=lambda a: a["keywords"])
    assert len(result) == 2
    assert result[0]["keywords"] == "a"
    assert result[0]["count"] == 5
    assert result[0]["time"] == 200
    assert result[0]["messages"] == ["m1", "m2", "m3"]
