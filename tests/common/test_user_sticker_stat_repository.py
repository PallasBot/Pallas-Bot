from __future__ import annotations

from contextlib import asynccontextmanager

import pytest
from sqlalchemy import create_engine
from sqlalchemy.dialects.postgresql import dialect as postgresql_dialect
from sqlalchemy.orm import Session

from pallas.core.foundation.db.repository_pg import Base
from pallas.core.foundation.db.user_sticker_stat_repository import UserStickerStatRepository


def test_repository_can_be_constructed_without_initializing_database() -> None:
    assert UserStickerStatRepository() is not None


def test_postgresql_increment_statement_adds_one_on_conflict() -> None:
    statement = UserStickerStatRepository.increment_statement(
        group_id=1, user_id=2, content_hash="a" * 64, sent_at=100, now=200, dialect_name="postgresql"
    )

    sql = str(statement.compile(dialect=postgresql_dialect()))
    assert "ON CONFLICT (group_id, user_id, content_hash) DO UPDATE" in sql
    assert "send_count = (user_sticker_stat.send_count + " in sql
    assert "last_sent_at = " in sql


class AsyncSqliteSession:
    def __init__(self, session: Session) -> None:
        self._session = session
        self.bind = session.bind

    async def execute(self, *args, **kwargs):
        return self._session.execute(*args, **kwargs)

    def get_bind(self):
        return self._session.get_bind()

    async def commit(self) -> None:
        self._session.commit()


@asynccontextmanager
async def sqlite_session_scope(engine):
    with Session(engine) as session:
        yield AsyncSqliteSession(session)


@pytest.fixture
def sqlite_repository():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    yield UserStickerStatRepository(lambda: sqlite_session_scope(engine)), engine
    engine.dispose()


@pytest.mark.asyncio
async def test_sqlite_increment_accumulates_and_lists_group_candidates(sqlite_repository) -> None:
    repository, _ = sqlite_repository

    await repository.increment(group_id=1, user_id=10, content_hash="a" * 64, sent_at=100)
    await repository.increment(group_id=1, user_id=10, content_hash="a" * 64, sent_at=200)
    await repository.increment(group_id=1, user_id=10, content_hash="a" * 64, sent_at=300, count=3)
    await repository.increment(group_id=1, user_id=11, content_hash="b" * 64, sent_at=150)
    await repository.increment(group_id=2, user_id=10, content_hash="a" * 64, sent_at=120)

    stat = await repository.get(group_id=1, user_id=10, content_hash="a" * 64)
    assert stat is not None
    assert stat.send_count == 5
    assert stat.last_sent_at == 300

    candidates = await repository.list_group_candidates(group_id=1, min_count=2, limit=5)
    assert [(int(row.user_id), str(row.content_hash), int(row.send_count)) for row in candidates] == [(10, "a" * 64, 5)]
    assert len(await repository.list_group_candidates(group_id=1, min_count=1, limit=5)) == 2
    assert await repository.list_group_candidates(group_id=2, min_count=5, limit=5) == []


@pytest.mark.asyncio
async def test_mongo_repository_matches_increment_contract(beanie_fixture) -> None:
    from pallas.core.foundation.db.modules import UserStickerStat
    from pallas.core.foundation.db.repository_impl import MongoUserStickerStatRepository

    repository = MongoUserStickerStatRepository()

    await repository.increment(group_id=1, user_id=10, content_hash="c" * 64, sent_at=100)
    await repository.increment(group_id=1, user_id=10, content_hash="c" * 64, sent_at=300, count=2)
    await repository.increment(group_id=1, user_id=12, content_hash="d" * 64, sent_at=200)

    stat = await repository.get(group_id=1, user_id=10, content_hash="c" * 64)
    assert stat is not None
    assert stat.send_count == 3
    assert stat.last_sent_at == 300

    candidates = await repository.list_group_candidates(group_id=1, min_count=2, limit=5)
    assert [(int(row.user_id), str(row.content_hash)) for row in candidates] == [(10, "c" * 64)]
    raw = await UserStickerStat.get_pymongo_collection().find_one({"group_id": 1, "user_id": 10})
    assert raw is not None
    assert raw["send_count"] == 3


def test_user_sticker_stat_repository_factory_selects_mongo(monkeypatch: pytest.MonkeyPatch) -> None:
    import pallas.core.foundation.db as db
    from pallas.core.foundation.db.repository_impl import MongoUserStickerStatRepository

    monkeypatch.setattr(db, "get_db_backend", lambda: "mongodb")

    assert isinstance(db.make_user_sticker_stat_repository(), MongoUserStickerStatRepository)
