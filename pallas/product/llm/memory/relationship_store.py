"""关系备注层存储：按 (bot, group, user) upsert/校正、带衰减的检索与裁剪。

写入：同一对象重复教导走 upsert（覆盖正文、刷新时间、权重回升），实现「校正」。
衰减：检索时按距上次更新的天数指数衰减权重；低于阈值视为过期、惰性裁剪。
"""

from __future__ import annotations

import math
import time

from sqlalchemy import delete, select

from pallas.core.foundation.db.repository_pg import LlmRelationshipNoteRow, get_session, is_pg_initialized
from pallas.core.foundation.db.runtime import is_postgresql_backend
from pallas.product.llm.config import LlmConfig, get_llm_config
from pallas.product.llm.memory.relationship import normalize_relationship_note
from pallas.product.llm.session_store import normalize_group_scope
from pallas.product.persona.prompt_guard import sanitize_prompt_literal

_DAY_SEC = 86400.0


def is_relationship_store_available() -> bool:
    cfg = get_llm_config()
    return cfg.llm_relationship_notes_enabled and is_postgresql_backend() and is_pg_initialized()


def decayed_weight(weight: float, updated_at: int, *, half_life_days: float, now: int | None = None) -> float:
    """按半衰期对权重做指数衰减。half_life_days<=0 表示不衰减。"""
    if half_life_days <= 0:
        return float(weight)
    elapsed_days = max(0.0, (float(now or int(time.time())) - float(updated_at)) / _DAY_SEC)
    return float(weight) * math.pow(0.5, elapsed_days / half_life_days)


async def save_relationship_note(
    bot_id: int,
    group_id: int | None,
    user_id: int,
    content: str,
    *,
    source: str = "teach",
    cfg: LlmConfig | None = None,
) -> bool:
    if not is_relationship_store_available() or not user_id:
        return False
    c = cfg or get_llm_config()
    safe_content = normalize_relationship_note(content, max_len=c.llm_relationship_content_max_len)
    if not safe_content:
        return False
    scope_gid = normalize_group_scope(group_id)
    now = int(time.time())
    safe_source = sanitize_prompt_literal(source, max_len=16) or "teach"
    async with get_session() as session:
        existing = (
            await session.execute(
                select(LlmRelationshipNoteRow).where(
                    LlmRelationshipNoteRow.bot_id == int(bot_id),
                    LlmRelationshipNoteRow.group_id == scope_gid,
                    LlmRelationshipNoteRow.user_id == int(user_id),
                )
            )
        ).scalar_one_or_none()
        if existing is not None:
            existing.content = safe_content
            existing.source = safe_source
            existing.weight = 1.0
            existing.updated_at = now
        else:
            session.add(
                LlmRelationshipNoteRow(
                    bot_id=int(bot_id),
                    group_id=scope_gid,
                    user_id=int(user_id),
                    content=safe_content,
                    source=safe_source,
                    weight=1.0,
                    created_at=now,
                    updated_at=now,
                )
            )
        await session.commit()
    return True


async def retrieve_relationship_note(
    bot_id: int,
    group_id: int | None,
    user_id: int,
    *,
    cfg: LlmConfig | None = None,
) -> str | None:
    """取当前对象的关系备注；权重衰减到阈值以下则视为过期，返回 None。"""
    if not is_relationship_store_available() or not user_id:
        return None
    c = cfg or get_llm_config()
    scope_gid = normalize_group_scope(group_id)
    now = int(time.time())
    async with get_session(read_only=True) as session:
        row = (
            await session.execute(
                select(LlmRelationshipNoteRow).where(
                    LlmRelationshipNoteRow.bot_id == int(bot_id),
                    LlmRelationshipNoteRow.group_id == scope_gid,
                    LlmRelationshipNoteRow.user_id == int(user_id),
                )
            )
        ).scalar_one_or_none()
    if row is None:
        return None
    weight = decayed_weight(
        float(row.weight or 0.0),
        int(row.updated_at or 0),
        half_life_days=c.llm_relationship_half_life_days,
        now=now,
    )
    if weight < c.llm_relationship_min_weight:
        return None
    content = str(row.content or "").strip()
    return content or None


async def trim_relationship_notes(bot_id: int, group_id: int | None, *, cfg: LlmConfig | None = None) -> int:
    """惰性裁剪：删除衰减到阈值以下的过期关系备注，返回删除条数。"""
    if not is_relationship_store_available():
        return 0
    c = cfg or get_llm_config()
    scope_gid = normalize_group_scope(group_id)
    now = int(time.time())
    stale_ids: list[int] = []
    async with get_session() as session:
        rows = (
            (
                await session.execute(
                    select(LlmRelationshipNoteRow).where(
                        LlmRelationshipNoteRow.bot_id == int(bot_id),
                        LlmRelationshipNoteRow.group_id == scope_gid,
                    )
                )
            )
            .scalars()
            .all()
        )
        for row in rows:
            weight = decayed_weight(
                float(row.weight or 0.0),
                int(row.updated_at or 0),
                half_life_days=c.llm_relationship_half_life_days,
                now=now,
            )
            if weight < c.llm_relationship_min_weight:
                stale_ids.append(int(row.id))
        if stale_ids:
            await session.execute(delete(LlmRelationshipNoteRow).where(LlmRelationshipNoteRow.id.in_(stale_ids)))
            await session.commit()
    return len(stale_ids)


async def list_relationship_notes(
    bot_id: int,
    group_id: int | None,
    *,
    query: str = "",
    limit: int = 50,
) -> list[dict[str, object]]:
    if not is_relationship_store_available():
        return []
    max_limit = max(1, min(int(limit), 200))
    async with get_session(read_only=True) as session:
        stmt = select(LlmRelationshipNoteRow).where(LlmRelationshipNoteRow.bot_id == int(bot_id))
        if group_id is not None:
            stmt = stmt.where(LlmRelationshipNoteRow.group_id == normalize_group_scope(group_id))
        rows = (
            (
                await session.execute(
                    stmt.order_by(
                        LlmRelationshipNoteRow.updated_at.desc(),
                        LlmRelationshipNoteRow.id.desc(),
                    ).limit(max_limit * 4)
                )
            )
            .scalars()
            .all()
        )
    needle = str(query or "").strip().casefold()
    items: list[dict[str, object]] = []
    for row in rows:
        content = str(row.content or "").strip()
        source = str(row.source or "").strip() or "teach"
        if needle and needle not in content.casefold() and needle not in source.casefold():
            continue
        items.append({
            "id": int(row.id),
            "bot_id": int(row.bot_id),
            "group_id": int(row.group_id),
            "user_id": int(row.user_id),
            "content": content,
            "source": source,
            "weight": float(row.weight or 0.0),
            "created_at": int(row.created_at or 0),
            "updated_at": int(row.updated_at or 0),
        })
        if len(items) >= max_limit:
            break
    return items


async def delete_relationship_note(note_id: int, *, bot_id: int | None = None) -> bool:
    if not is_relationship_store_available():
        return False
    async with get_session() as session:
        row = (
            await session.execute(
                select(LlmRelationshipNoteRow).where(
                    LlmRelationshipNoteRow.id == int(note_id),
                )
            )
        ).scalar_one_or_none()
        if row is None:
            return False
        if bot_id is not None and int(row.bot_id or 0) != int(bot_id):
            return False
        await session.delete(row)
        await session.commit()
    return True
