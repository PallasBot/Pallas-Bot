from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from pallas.product.llm.corpus_contamination import (
    CORPUS_LEARN_BLOCK_PHRASES,
    CORPUS_LEARN_EXCLUDE_SUBSTR,
    FEEDBACK_META_BLOCK_PHRASES,
    build_mongo_substr_query,
    is_corpus_learn_safe,
    is_expression_reference_safe,
    is_feedback_reply_collectable,
    match_corpus_learn_block,
    match_feedback_meta_block,
    prune_polluted_context_answers,
    reject_corpus_learn_message,
    run_mongo_corpus_contamination_cleanup,
)


def test_match_corpus_learn_block_celebration_template() -> None:
    hit = match_corpus_learn_block("晚安！希望每个庆典都能顺利举行")
    assert hit is not None
    assert hit.phrase == "希望每个庆典"


def test_match_corpus_learn_block_respects_exclude() -> None:
    text = "流媒体解析bot为您服务，链接已生成"
    assert match_corpus_learn_block(text) is None


def test_match_feedback_meta_block() -> None:
    hit = match_feedback_meta_block("因为今天天气不错")
    assert hit is not None
    assert hit.phrase == "因为"


def test_is_feedback_reply_collectable_blocks_meta_and_contamination() -> None:
    assert is_feedback_reply_collectable("通常我会这么说") is False
    assert is_feedback_reply_collectable("庆典感满满") is False
    assert is_feedback_reply_collectable("行，懂了") is True


def test_is_expression_reference_safe_blocks_contaminated_hint(monkeypatch) -> None:
    from pallas.product.llm.config import LlmConfig

    monkeypatch.setattr(
        "pallas.product.llm.config.get_llm_config",
        lambda: LlmConfig(llm_corpus_learn_guard_enabled=True),
    )
    assert is_expression_reference_safe("希望每个庆典都能顺利") is False
    assert is_expression_reference_safe("这也太黑了吧") is True


def test_reject_corpus_learn_message(monkeypatch) -> None:
    from pallas.product.llm.config import LlmConfig

    monkeypatch.setattr(
        "pallas.product.llm.config.get_llm_config",
        lambda: LlmConfig(llm_corpus_learn_guard_enabled=True),
    )
    assert reject_corpus_learn_message("谢谢您的陪伴", source="test") is True
    assert reject_corpus_learn_message("好的", source="test") is False


def test_is_corpus_learn_safe_honors_guard_flag(monkeypatch) -> None:
    from pallas.product.llm.config import LlmConfig

    monkeypatch.setattr(
        "pallas.product.llm.config.get_llm_config",
        lambda: LlmConfig(llm_corpus_learn_guard_enabled=False),
    )
    assert is_corpus_learn_safe("希望每个庆典") is True


def test_phrase_lists_not_empty() -> None:
    assert CORPUS_LEARN_BLOCK_PHRASES
    assert CORPUS_LEARN_EXCLUDE_SUBSTR
    assert FEEDBACK_META_BLOCK_PHRASES


def test_build_mongo_substr_query() -> None:
    query = build_mongo_substr_query("plain_text", ("希望每个庆典",), ("流媒体解析bot",))
    assert "$and" in query


def test_prune_polluted_context_answers() -> None:
    answers = [
        {"keywords": "a", "group_id": 1, "messages": ["好的", "希望每个庆典都能顺利举行"]},
        {"keywords": "b", "group_id": 1, "messages": ["庆典感满满"]},
    ]
    kept, removed_messages, removed_answers = prune_polluted_context_answers(answers)
    assert removed_messages == 2
    assert removed_answers == 1
    assert len(kept) == 1
    assert kept[0]["messages"] == ["好的"]


@pytest.mark.asyncio
async def test_run_mongo_corpus_contamination_cleanup(beanie_fixture, monkeypatch) -> None:
    from pallas.core.foundation.db.modules import Answer, Context, Message

    async def noop_init() -> None:
        return None

    monkeypatch.setattr("pallas.core.foundation.db.is_mongodb_backend", lambda: True)
    monkeypatch.setattr("pallas.core.foundation.db.init_mongodb_db", noop_init)

    await Context(
        keywords="ctx-1",
        answers=[Answer(keywords="a", group_id=1, messages=["好的", "谢谢您的陪伴"])],
    ).insert()
    await Message(
        bot_id=1,
        group_id=1,
        user_id=2,
        raw_message="希望每个庆典",
        plain_text="希望每个庆典都能顺利举行",
        keywords="k",
    ).insert()

    report = await run_mongo_corpus_contamination_cleanup(apply=True, preview_limit=0)

    assert report.deleted_answer_messages == 1
    assert report.deleted_empty_answers == 0
    assert report.deleted_message_history == 1

    found = await Context.find_one(Context.keywords == "ctx-1")
    assert found is not None
    assert found.answers[0].messages == ["好的"]
    assert await Message.find(Message.plain_text == "希望每个庆典都能顺利举行").count() == 0


@pytest.mark.asyncio
async def test_run_pg_corpus_contamination_cleanup_caps_per_round_delete(monkeypatch) -> None:
    """单轮删除量必须被 max_delete 限制，剩余候选留待下一轮，避免长事务与死元组堆积。"""
    from pallas.product.llm import corpus_contamination as mod

    async def fake_ready(_backend: str) -> bool:
        return True

    async def fake_ensure(_backend: str) -> None:
        return None

    executed: list[str] = []

    class FakeSession:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args: object) -> None:
            return None

        async def execute(self, stmt, *_params):
            return SimpleNamespace(rowcount=0)

        async def commit(self) -> None:
            return None

    class FakeRow:
        def __getitem__(self, _idx: int):
            return 1

    class FakeSelect:
        def __init__(self, rows: list[FakeRow]) -> None:
            self._rows = rows

        def all(self):
            return self._rows

    class FakeWriteSession(FakeSession):
        def __init__(self) -> None:
            self.deleted_total = 0

        async def execute(self, stmt, params=None):
            executed.append(str(stmt)[:60])
            sql = str(stmt)
            if "DELETE FROM message" in sql:
                ids = (params or {}).get("ids") or []
                self.deleted_total += len(ids)
                return SimpleNamespace(rowcount=len(ids))
            return SimpleNamespace(rowcount=0)

    class FakeReadSession(FakeSession):
        async def execute(self, stmt, *_params):
            sql = str(stmt)
            if "context_answer_message" in sql:
                return FakeSelect([])
            return FakeSelect([FakeRow() for _ in range(250)])

    write_session = FakeWriteSession()

    def fake_get_session(*_args, **_kwargs):
        return write_session if not _kwargs.get("read_only") else FakeReadSession()

    monkeypatch.setattr("pallas.core.foundation.db.ensure_runtime_storage_ready", fake_ensure)
    monkeypatch.setattr("pallas.core.foundation.db.is_postgresql_backend", lambda: True)
    monkeypatch.setattr(mod, "corpus_cleanup_max_delete_per_round", lambda: 120)
    monkeypatch.setattr(mod, "corpus_cleanup_message_history_enabled", lambda: True)
    monkeypatch.setattr("pallas.core.foundation.db.repository_pg.get_session", fake_get_session)
    monkeypatch.setattr("pallas.core.foundation.db.repository_pg.vacuum_message_table", AsyncMock())
    monkeypatch.setattr(
        "pallas.core.foundation.db.repository_pg.clear_reply_query_snapshot_cache",
        AsyncMock(),
    )

    report = await mod.run_pg_corpus_contamination_cleanup(apply=True, preview_limit=0)

    assert write_session.deleted_total == 120  # 250 条候选被上限压到只删 120 条
    assert report.deleted_message_history == 120
    assert report.deleted_answer_messages == 0
