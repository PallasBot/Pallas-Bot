"""
Mongo → PG 迁移脚本健壮性测试。

fixture（``pg_env`` / 迁移模块加载）来自 ``tests/common/conftest.py``；未设置
``PG_TEST_DSN`` 时依赖 pg_env 的用例自动 skip，纯函数用例（defensive helpers、
去重聚合）无 DB 依赖、始终会跑。Mongo 侧以下方 ``_FakeDb`` 代替真实实例。
"""

from __future__ import annotations

from .conftest import _load_migrate_module


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
# Defensive helpers（纯函数测试，无需 DB）
# ---------------------------------------------------------------------------


def test_defensive_helpers_handle_garbage():
    """_as_int/_as_bool/_as_list/_as_dict/_strip_null 对 None、错类型、嵌套容器都要给合理默认。"""
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


async def test_stream_batches_orders_by_id_and_paginates():
    """_stream_batches 按 _id 升序分页，并支持从任意 last_id 处续传。"""
    migrate = _load_migrate_module()
    from bson import ObjectId

    ids = [ObjectId() for _ in range(25)]
    docs = [{"_id": ids[i], "n": i} for i in range(25)]
    col = _FakeCollection(docs)

    seen: list[int] = []
    async for batch in migrate._stream_batches(col, None, batch_size=10):
        seen.extend(d["n"] for d in batch)
    assert seen == list(range(25))

    resume_from = str(ids[9])
    seen2: list[int] = []
    async for batch in migrate._stream_batches(col, resume_from, batch_size=10):
        seen2.extend(d["n"] for d in batch)
    assert seen2 == list(range(10, 25))


async def test_dedupe_answers_aggregates_correctly():
    """_dedupe_answers 按 (group_id, keywords) 聚合：count 累加、time 取 max、messages 合并。"""
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


# ---------------------------------------------------------------------------
# Context 迁移：脏数据 + keywords 合并 + \x00
# ---------------------------------------------------------------------------


async def test_migrate_context_merges_duplicate_keywords(pg_env):
    """同 keywords_hash 的多条 Mongo 文档在单批内合并成 1 个 Context，answers/bans 正确聚合。"""
    from bson import ObjectId

    from src.common.db.repository_pg import ContextAnswerMessageRow, ContextAnswerRow, ContextBanRow, ContextRow

    migrate = pg_env["migrate"]
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
            "keywords": "dup\x00kw",  # 与上一条同 keywords
            "time": 200,
            "trigger_count": 1,
            "clear_time": 50,
            "answers": [
                {"keywords": "a", "group_id": 1, "count": 1, "time": 200, "messages": ["m3"]},
                {"keywords": "c", "group_id": 2, "count": 1, "time": 200, "messages": []},
            ],
            "ban": [],
        },
        # 空 keywords 应被 skip
        {"_id": ObjectId(), "keywords": "", "time": 0, "answers": [], "ban": []},
        # answers 里混入非 dict，应被忽略但 context 本身照常写入
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
        assert len(ctxs) == 2, [c.keywords for c in ctxs]
        dup = next(c for c in ctxs if "dup" in c.keywords)
        assert "\x00" not in dup.keywords
        assert dup.time == 200
        assert dup.trigger_count == 3
        assert dup.clear_time == 50

        ans = (
            await session.execute(select(ContextAnswerRow).where(ContextAnswerRow.context_id == dup.id))
        ).scalars().all()
        assert len(ans) == 2
        ans_a = next(a for a in ans if a.group_id == 1 and a.keywords == "a")
        assert ans_a.count == 3
        assert ans_a.time == 200

        msgs = (
            await session.execute(
                select(ContextAnswerMessageRow).where(ContextAnswerMessageRow.answer_id == ans_a.id)
            )
        ).scalars().all()
        all_msgs = {m.message for m in msgs}
        assert all_msgs == {"m1", "m2", "m3"}
        assert all("\x00" not in m for m in all_msgs)

        bans = (
            await session.execute(select(ContextBanRow).where(ContextBanRow.context_id == dup.id))
        ).scalars().all()
        assert len(bans) == 1
        assert "\x00" not in bans[0].reason


# ---------------------------------------------------------------------------
# Message 迁移 + 断点续传
# ---------------------------------------------------------------------------


async def test_migrate_message_resumable(pg_env):
    """migration_state 已写 last_id 时，重跑只补未迁部分、不产生重复。"""
    from bson import ObjectId
    from sqlalchemy import func, insert as sa_insert, select

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

    # 人为写入"前 5 条已迁 + state 停在第 5 条"的状态
    async with pg_env["sf"]() as session:
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

    await migrate._migrate_message(
        db, pg_env["sf"], MessageRow, pg_env["pg_insert"], batch_size=100, dry_run=False
    )

    async with pg_env["sf"]() as session:
        total = (await session.execute(select(func.count()).select_from(MessageRow))).scalar_one()
        assert total == 10
        rows = (await session.execute(select(MessageRow).order_by(MessageRow.time))).scalars().all()
        assert all("\x00" not in r.raw_message for r in rows)


async def test_migrate_message_dirty_rows_counted(pg_env):
    """defensive helpers 把错类型字段（如 group_id='not-a-number'）兜底成默认值后仍入库，保证单条脏数据不拖垮整个 batch。"""
    from bson import ObjectId
    from sqlalchemy import func, select

    from src.common.db.repository_pg import MessageRow

    migrate = pg_env["migrate"]

    docs = [
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
        {
            "_id": ObjectId(),
            "group_id": "not-a-number",  # 错类型：应被 _as_int 兜底成 0
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
    async with pg_env["sf"]() as session:
        total = (await session.execute(select(func.count()).select_from(MessageRow))).scalar_one()
    assert total == 2
    assert stats.failed == 0


# ---------------------------------------------------------------------------
# BlackList / Config 迁移
# ---------------------------------------------------------------------------


async def test_migrate_blacklist_rerun_idempotent(pg_env):
    """迁完一次后重跑不产生重复写入；\\x00 字段已被剥除。"""
    from bson import ObjectId
    from sqlalchemy import select

    from src.common.db.repository_pg import BlackListRow

    migrate = pg_env["migrate"]
    docs = [
        {"_id": ObjectId(), "group_id": 1, "answers": ["a\x00", "b"], "answers_reserve": []},
        {"_id": ObjectId(), "group_id": 2, "answers": [], "answers_reserve": ["x"]},
    ]
    db = _FakeDb({"blacklist": docs})

    await migrate._migrate_blacklist(db, pg_env["sf"], BlackListRow, pg_env["pg_insert"], batch_size=100, dry_run=False)
    await migrate._migrate_blacklist(db, pg_env["sf"], BlackListRow, pg_env["pg_insert"], batch_size=100, dry_run=False)

    async with pg_env["sf"]() as session:
        rows = (await session.execute(select(BlackListRow).order_by(BlackListRow.group_id))).scalars().all()
        assert len(rows) == 2
        assert rows[0].answers == ["a", "b"]
        assert rows[1].answers_reserve == ["x"]


async def test_migrate_bot_config_handles_auto_accept_legacy(pg_env):
    """旧 schema 只有 auto_accept（仅对 group 生效），迁移要能 fallback；admins 里非法项直接跳过。"""
    from bson import ObjectId
    from sqlalchemy import select

    from src.common.db.repository_pg import BotConfigRow

    migrate = pg_env["migrate"]
    docs = [
        {"_id": ObjectId(), "account": 1001, "auto_accept": True, "admins": [1, "2", "bad"], "taken_name": {"100": 1}, "drunk": {"200": 0.5}},
        {"_id": ObjectId(), "account": 1002, "auto_accept_group": False, "auto_accept_friend": True},
    ]
    db = _FakeDb({"config": docs})

    await migrate._migrate_bot_config(db, pg_env["sf"], BotConfigRow, pg_env["pg_insert"], batch_size=100, dry_run=False)

    async with pg_env["sf"]() as session:
        rows = (await session.execute(select(BotConfigRow).order_by(BotConfigRow.account))).scalars().all()
        assert rows[0].account == 1001
        assert rows[0].auto_accept_group is True
        assert rows[0].auto_accept_friend is False
        assert rows[0].admins == [1, 2]
        assert rows[1].auto_accept_group is False
        assert rows[1].auto_accept_friend is True


async def test_migrate_image_cache_upsert(pg_env):
    """同 cq_code 多条在单批内 upsert 只剩最后一条；空 cq_code 脏数据被计入 failed。"""
    from bson import ObjectId
    from sqlalchemy import select

    from src.common.db.repository_pg import ImageCacheRow

    migrate = pg_env["migrate"]
    docs = [
        {"_id": ObjectId(), "cq_code": "[CQ:image,file=a.image]", "base64_data": None, "ref_times": 1, "date": 20250101},
        {"_id": ObjectId(), "cq_code": "[CQ:image,file=a.image]", "base64_data": "b64", "ref_times": 5, "date": 20250110},
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
    assert stats.failed >= 1
