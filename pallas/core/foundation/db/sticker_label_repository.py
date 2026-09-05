"""表情语义标签的 PostgreSQL/SQLite 仓储。"""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import case, delete, func, or_, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from pallas.core.foundation.db.repository_pg import StickerLabelRow, get_session

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from pallas.product.llm.sticker_labels import StickerSemanticLabel


class StickerLabelRepository:
    """只持久化内容哈希和受控标签，不接收图片或 CQ 码。"""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession] | None = None) -> None:
        self._session_factory = session_factory

    def session(self):
        return self._session_factory() if self._session_factory is not None else get_session()

    @staticmethod
    def upsert_statement(label: StickerSemanticLabel, *, dialect_name: str):
        values = {
            "content_hash": label.content_hash,
            "is_sticker": label.is_sticker,
            "confidence": label.confidence,
            "prompt_version": label.prompt_version,
            "labeled_at": label.labeled_at,
            "label_json": label.model_dump(mode="json"),
        }
        if dialect_name == "postgresql":
            stmt = pg_insert(StickerLabelRow).values(**values)
        elif dialect_name == "sqlite":
            stmt = sqlite_insert(StickerLabelRow).values(**values)
        else:
            raise RuntimeError(f"unsupported sticker label dialect: {dialect_name}")
        return stmt.on_conflict_do_update(
            index_elements=["content_hash"],
            set_={
                "is_sticker": stmt.excluded.is_sticker,
                "confidence": stmt.excluded.confidence,
                "prompt_version": stmt.excluded.prompt_version,
                "labeled_at": stmt.excluded.labeled_at,
                "label_json": stmt.excluded.label_json,
            },
        )

    async def get(self, content_hash: str) -> StickerSemanticLabel | None:
        from pallas.product.llm.sticker_labels import StickerSemanticLabel

        async with self.session() as session:
            row = await session.get(StickerLabelRow, content_hash)
            if row is None:
                return None
            return StickerSemanticLabel.model_validate(row.label_json)

    async def upsert(self, label: StickerSemanticLabel) -> None:
        async with self.session() as session:
            dialect_name = session.get_bind().dialect.name
            await session.execute(self.upsert_statement(label, dialect_name=dialect_name))
            await session.commit()

    async def list_labels(self, *, limit: int = 100, offset: int = 0) -> list[StickerSemanticLabel]:
        from pallas.product.llm.sticker_labels import StickerSemanticLabel

        async with self.session() as session:
            rows = (
                await session.execute(
                    select(StickerLabelRow)
                    .order_by(StickerLabelRow.labeled_at.desc(), StickerLabelRow.content_hash)
                    .offset(max(0, offset))
                    .limit(max(1, limit))
                )
            ).scalars()
            return [StickerSemanticLabel.model_validate(row.label_json) for row in rows]

    async def stats(self, *, min_confidence: float = 0.6, current_prompt_version: int | None = None) -> dict[str, int]:
        async with self.session() as session:
            total, sticker, low_confidence, current_version = (
                await session.execute(
                    select(
                        func.count(),
                        func.coalesce(func.sum(case((StickerLabelRow.is_sticker, 1), else_=0)), 0),
                        func.coalesce(func.sum(case((StickerLabelRow.confidence < min_confidence, 1), else_=0)), 0),
                        func.coalesce(
                            func.sum(case((StickerLabelRow.prompt_version == current_prompt_version, 1), else_=0)),
                            0,
                        ),
                    )
                )
            ).one()
        total_int = int(total)
        sticker_int = int(sticker)
        result = {
            "total": total_int,
            "sticker": sticker_int,
            "not_sticker": total_int - sticker_int,
            "low_confidence": int(low_confidence),
        }
        if current_prompt_version is not None:
            result["current_version"] = int(current_version)
        return result

    async def list_relabel_candidates(
        self,
        *,
        min_confidence: float,
        current_prompt_version: int,
        limit: int = 200,
    ) -> list[StickerSemanticLabel]:
        from pallas.product.llm.sticker_labels import StickerSemanticLabel

        async with self.session() as session:
            rows = (
                await session.execute(
                    select(StickerLabelRow)
                    .where(
                        or_(
                            StickerLabelRow.confidence < min_confidence,
                            StickerLabelRow.prompt_version < current_prompt_version,
                        )
                    )
                    .order_by(StickerLabelRow.labeled_at, StickerLabelRow.content_hash)
                    .limit(max(1, int(limit)))
                )
            ).scalars()
            return [StickerSemanticLabel.model_validate(row.label_json) for row in rows]

    async def delete(self, content_hash: str) -> bool:
        async with self.session() as session:
            result = await session.execute(delete(StickerLabelRow).where(StickerLabelRow.content_hash == content_hash))
            await session.commit()
        return bool(result.rowcount)
