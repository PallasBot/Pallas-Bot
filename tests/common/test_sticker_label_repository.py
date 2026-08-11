from __future__ import annotations

from contextlib import asynccontextmanager

import pytest
from sqlalchemy import create_engine, inspect
from sqlalchemy.dialects.postgresql import dialect as postgresql_dialect
from sqlalchemy.orm import Session

from pallas.core.foundation.db.repository_pg import Base
from pallas.core.foundation.db.sticker_label_repository import StickerLabelRepository
from pallas.product.llm.sticker_labels import StickerSemanticLabel


def test_repository_can_be_constructed_without_initializing_database() -> None:
    assert StickerLabelRepository() is not None


def test_postgresql_upsert_statement_updates_conflicting_content_hash() -> None:
    label = StickerSemanticLabel(content_hash="a" * 64, is_sticker=False, labeled_at=1)

    statement = StickerLabelRepository.upsert_statement(label, dialect_name="postgresql")

    sql = str(statement.compile(dialect=postgresql_dialect()))
    assert "ON CONFLICT (content_hash) DO UPDATE" in sql
    assert "label_json = excluded.label_json" in sql
    assert "labeled_at = excluded.labeled_at" in sql


class AsyncSqliteSession:
    def __init__(self, session: Session) -> None:
        self._session = session
        self.bind = session.bind

    async def get(self, *args, **kwargs):
        return self._session.get(*args, **kwargs)

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
    yield StickerLabelRepository(lambda: sqlite_session_scope(engine)), engine
    engine.dispose()


@pytest.mark.asyncio
async def test_sqlite_repository_round_trips_negative_label_and_reports_stats(sqlite_repository) -> None:
    repository, engine = sqlite_repository
    label = StickerSemanticLabel(
        content_hash="c" * 64,
        is_sticker=False,
        confidence=0.95,
        model="vision-test",
        prompt_version=4,
        labeled_at=10,
    )

    await repository.upsert(label)

    assert await repository.get(label.content_hash) == label
    assert await repository.list_labels() == [label]
    assert await repository.stats() == {
        "total": 1,
        "sticker": 0,
        "not_sticker": 1,
        "low_confidence": 0,
    }
    columns = {column["name"] for column in inspect(engine).get_columns("sticker_label")}
    assert {"image", "image_bytes", "blob_data", "cq_code"}.isdisjoint(columns)


@pytest.mark.asyncio
async def test_sqlite_repository_upsert_replaces_the_same_content_hash(sqlite_repository) -> None:
    repository, _ = sqlite_repository
    initial = StickerSemanticLabel(content_hash="d" * 64, is_sticker=False, confidence=0.9, prompt_version=1)
    replacement = initial.model_copy(
        update={"is_sticker": True, "confidence": 0.8, "prompt_version": 2, "labeled_at": 11}
    )

    await repository.upsert(initial)
    await repository.upsert(replacement)

    assert await repository.get(initial.content_hash) == replacement
    assert await repository.list_labels() == [replacement]
    assert await repository.stats() == {
        "total": 1,
        "sticker": 1,
        "not_sticker": 0,
        "low_confidence": 0,
    }


@pytest.mark.asyncio
async def test_mongo_repository_matches_label_contract_without_media_fields(beanie_fixture) -> None:
    from pallas.core.foundation.db.modules import StickerLabel
    from pallas.core.foundation.db.repository_impl import MongoStickerLabelRepository

    repository = MongoStickerLabelRepository()
    negative = StickerSemanticLabel(content_hash="e" * 64, is_sticker=False, confidence=0.5, labeled_at=10)
    positive = StickerSemanticLabel(content_hash="f" * 64, is_sticker=True, confidence=0.9, labeled_at=11)

    await repository.upsert(negative)
    await repository.upsert(positive)
    await repository.upsert(negative.model_copy(update={"confidence": 0.8, "labeled_at": 12}))

    replacement = negative.model_copy(update={"confidence": 0.8, "labeled_at": 12})
    assert await repository.get(negative.content_hash) == replacement
    assert await repository.list_labels() == [
        replacement,
        positive,
    ]
    assert await repository.stats(min_confidence=0.85) == {
        "total": 2,
        "sticker": 1,
        "not_sticker": 1,
        "low_confidence": 1,
    }
    raw = await StickerLabel.get_pymongo_collection().find_one({"content_hash": negative.content_hash})
    assert raw is not None
    assert {"image", "image_bytes", "blob_data", "cq_code"}.isdisjoint(raw)


def test_sticker_label_repository_factory_selects_mongo(monkeypatch: pytest.MonkeyPatch) -> None:
    import pallas.core.foundation.db as db
    from pallas.core.foundation.db.repository_impl import MongoStickerLabelRepository

    monkeypatch.setattr(db, "get_db_backend", lambda: "mongodb")

    assert isinstance(db.make_sticker_label_repository(), MongoStickerLabelRepository)
