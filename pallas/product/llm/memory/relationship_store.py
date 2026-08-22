"""关系备注层存储：按 (bot, group, user) upsert/校正、带衰减的检索与裁剪。

写入：同一对象重复教导走 upsert（合并事实、刷新时间、权重回升），实现「校正」。
人对语气偏置：warmth_delta / assertiveness_delta，钳制在配置上限内。
衰减：检索时按距上次更新的天数指数衰减权重；低于阈值视为过期、惰性裁剪。
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass

from sqlalchemy import delete, select

from pallas.core.foundation.db.repository_pg import LlmRelationshipNoteRow, get_session
from pallas.product.llm.config import LlmConfig, get_llm_config
from pallas.product.llm.memory.relationship import (
    clamp_affinity,
    clamp_user_relationship_delta,
    decay_affinity_toward_neutral,
    merge_relationship_facts,
    normalize_relationship_note,
    prefer_relationship_source,
)
from pallas.product.llm.rage import RageState
from pallas.product.llm.session_backend import llm_product_storage_ready
from pallas.product.llm.session_store import normalize_group_scope
from pallas.product.persona.prompt_guard import sanitize_prompt_literal

_DAY_SEC = 86400.0


@dataclass(frozen=True, slots=True)
class RelationshipProfile:
    content: str = ""
    warmth_delta: float = 0.0
    assertiveness_delta: float = 0.0
    affinity: float = 0.0
    source: str = "auto"
    weight: float = 1.0
    rage: RageState = RageState()

    @property
    def has_facts(self) -> bool:
        return bool(str(self.content or "").strip())

    @property
    def has_affect(self) -> bool:
        return self.warmth_delta != 0.0 or self.assertiveness_delta != 0.0

    @property
    def has_affinity(self) -> bool:
        return self.affinity != 0.0


def is_relationship_store_available() -> bool:
    cfg = get_llm_config()
    return cfg.llm_relationship_notes_enabled and llm_product_storage_ready()


def is_rage_store_available() -> bool:
    return llm_product_storage_ready()


def _use_mongodb_backend() -> bool:
    from pallas.core.foundation.db.runtime import is_mongodb_backend

    return is_mongodb_backend()


def _use_postgresql_backend() -> bool:
    from pallas.core.foundation.db.runtime import is_postgresql_backend

    return is_postgresql_backend()


def decayed_weight(weight: float, updated_at: int, *, half_life_days: float, now: int | None = None) -> float:
    """按半衰期对权重做指数衰减。half_life_days<=0 表示不衰减。"""
    if half_life_days <= 0:
        return float(weight)
    elapsed_days = max(0.0, (float(now or int(time.time())) - float(updated_at)) / _DAY_SEC)
    return float(weight) * math.pow(0.5, elapsed_days / half_life_days)


def _delta_limit(cfg: LlmConfig) -> float:
    return float(getattr(cfg, "llm_relationship_affect_delta_max", 0.15) or 0.15)


def _affinity_limit(cfg: LlmConfig) -> float:
    return float(getattr(cfg, "llm_relationship_affinity_delta_max", 0.15) or 0.15)


async def upsert_relationship_profile(
    bot_id: int,
    group_id: int | None,
    user_id: int,
    *,
    content: str | None = None,
    source: str = "auto",
    warmth_delta_add: float = 0.0,
    assertiveness_delta_add: float = 0.0,
    affinity_delta_add: float = 0.0,
    merge_content: bool = True,
    cfg: LlmConfig | None = None,
) -> bool:
    """合并事实与人对偏置；content 为空时也可只更新 delta。"""
    if not is_relationship_store_available() or not user_id:
        return False
    if _use_mongodb_backend():
        from pallas.product.llm.memory.relationship_store_mongo import upsert_relationship_profile_mongo

        return await upsert_relationship_profile_mongo(
            bot_id,
            group_id,
            user_id,
            content=content,
            source=source,
            warmth_delta_add=warmth_delta_add,
            assertiveness_delta_add=assertiveness_delta_add,
            affinity_delta_add=affinity_delta_add,
            merge_content=merge_content,
            cfg=cfg,
        )
    if not _use_postgresql_backend():
        return False
    c = cfg or get_llm_config()
    incoming = normalize_relationship_note(content or "", max_len=c.llm_relationship_content_max_len)
    has_fact = bool(incoming)
    has_delta = warmth_delta_add != 0.0 or assertiveness_delta_add != 0.0 or affinity_delta_add != 0.0
    if not has_fact and not has_delta:
        return False
    scope_gid = normalize_group_scope(group_id)
    now = int(time.time())
    safe_source = sanitize_prompt_literal(source, max_len=16) or "auto"
    limit = _delta_limit(c)
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
            if has_fact:
                if merge_content:
                    existing.content = merge_relationship_facts(
                        str(existing.content or ""),
                        incoming,
                        max_len=c.llm_relationship_content_max_len,
                    )
                else:
                    existing.content = incoming
            existing.source = prefer_relationship_source(str(existing.source or ""), safe_source)
            existing.warmth_delta = clamp_user_relationship_delta(
                float(existing.warmth_delta or 0.0) + float(warmth_delta_add),
                limit=limit,
            )
            existing.assertiveness_delta = clamp_user_relationship_delta(
                float(existing.assertiveness_delta or 0.0) + float(assertiveness_delta_add),
                limit=limit,
            )
            existing.affinity = clamp_affinity(
                float(getattr(existing, "affinity", 0.0) or 0.0) + float(affinity_delta_add)
            )
            existing.weight = 1.0
            existing.updated_at = now
        else:
            session.add(
                LlmRelationshipNoteRow(
                    bot_id=int(bot_id),
                    group_id=scope_gid,
                    user_id=int(user_id),
                    content=incoming if has_fact else "",
                    source=safe_source,
                    weight=1.0,
                    warmth_delta=clamp_user_relationship_delta(float(warmth_delta_add), limit=limit),
                    assertiveness_delta=clamp_user_relationship_delta(
                        float(assertiveness_delta_add),
                        limit=limit,
                    ),
                    affinity=clamp_affinity(float(affinity_delta_add)),
                    created_at=now,
                    updated_at=now,
                )
            )
        await session.commit()
    return True


async def update_rage_state(
    bot_id: int,
    group_id: int | None,
    user_id: int,
    state: RageState,
) -> bool:
    """Persist rage fields without changing relationship facts or affinity."""
    if not is_rage_store_available() or not user_id:
        return False
    if _use_mongodb_backend():
        from pallas.product.llm.memory.relationship_store_mongo import update_rage_state_mongo

        return await update_rage_state_mongo(bot_id, group_id, user_id, state)
    if not _use_postgresql_backend():
        return False
    scope_gid = normalize_group_scope(group_id)
    now = int(time.time())
    async with get_session() as session:
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
            session.add(
                LlmRelationshipNoteRow(
                    bot_id=int(bot_id),
                    group_id=scope_gid,
                    user_id=int(user_id),
                    content="",
                    source="rage",
                    created_at=now,
                    updated_at=now,
                    rage=max(0, min(100, int(state.rage))),
                    rage_last_attack_at=int(state.last_attack_at),
                    rage_last_attack_message_id=int(state.last_attack_message_id),
                    rage_silenced_until=int(state.silenced_until),
                    rage_silence_reason=str(state.silence_reason or ""),
                )
            )
        else:
            row.rage = max(0, min(100, int(state.rage)))
            row.rage_last_attack_at = int(state.last_attack_at)
            row.rage_last_attack_message_id = int(state.last_attack_message_id)
            row.rage_silenced_until = int(state.silenced_until)
            row.rage_silence_reason = str(state.silence_reason or "")
            row.updated_at = now
        await session.commit()
    return True


async def clear_rage_state(bot_id: int, group_id: int | None, user_id: int) -> bool:
    return await update_rage_state(bot_id, group_id, user_id, RageState())


async def retrieve_rage_state(bot_id: int, group_id: int | None, user_id: int) -> RageState | None:
    if not is_rage_store_available() or not user_id:
        return None
    if _use_mongodb_backend():
        from pallas.product.llm.memory.relationship_store_mongo import retrieve_rage_state_mongo

        return await retrieve_rage_state_mongo(bot_id, group_id, user_id)
    if not _use_postgresql_backend():
        return None
    scope_gid = normalize_group_scope(group_id)
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
    return RageState(
        rage=max(0, min(100, int(getattr(row, "rage", 0) or 0))),
        last_attack_at=int(getattr(row, "rage_last_attack_at", 0) or 0),
        last_attack_message_id=int(getattr(row, "rage_last_attack_message_id", 0) or 0),
        silenced_until=int(getattr(row, "rage_silenced_until", 0) or 0),
        silence_reason=str(getattr(row, "rage_silence_reason", "") or ""),
    )


async def save_relationship_note(
    bot_id: int,
    group_id: int | None,
    user_id: int,
    content: str,
    *,
    source: str = "teach",
    cfg: LlmConfig | None = None,
) -> bool:
    return await upsert_relationship_profile(
        bot_id,
        group_id,
        user_id,
        content=content,
        source=source,
        merge_content=True,
        cfg=cfg,
    )


async def set_relationship_note_content(
    bot_id: int,
    group_id: int | None,
    user_id: int,
    content: str,
    *,
    cfg: LlmConfig | None = None,
) -> bool:
    """WebUI 覆盖：手动改写关系备注文本（不 merge、不动好感度）。"""
    if not is_relationship_store_available() or not user_id:
        return False
    if _use_mongodb_backend():
        from pallas.product.llm.memory.relationship_store_mongo import set_relationship_note_content_mongo

        return await set_relationship_note_content_mongo(bot_id, group_id, user_id, content, cfg=cfg)
    if not _use_postgresql_backend():
        return False
    c = cfg or get_llm_config()
    incoming = normalize_relationship_note(content or "", max_len=c.llm_relationship_content_max_len)
    scope_gid = normalize_group_scope(group_id)
    now = int(time.time())
    async with get_session() as session:
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
            return False
        row.content = incoming
        row.updated_at = now
        await session.commit()
    return True


async def retrieve_relationship_profile(
    bot_id: int,
    group_id: int | None,
    user_id: int,
    *,
    cfg: LlmConfig | None = None,
) -> RelationshipProfile | None:
    """取当前对象的关系档案；权重衰减到阈值以下则视为过期。"""
    if not is_relationship_store_available() or not user_id:
        return None
    if _use_mongodb_backend():
        from pallas.product.llm.memory.relationship_store_mongo import retrieve_relationship_profile_mongo

        return await retrieve_relationship_profile_mongo(bot_id, group_id, user_id, cfg=cfg)
    if not _use_postgresql_backend():
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
    warmth = clamp_user_relationship_delta(float(getattr(row, "warmth_delta", 0.0) or 0.0), limit=_delta_limit(c))
    assertiveness = clamp_user_relationship_delta(
        float(getattr(row, "assertiveness_delta", 0.0) or 0.0),
        limit=_delta_limit(c),
    )
    affinity = decay_affinity_toward_neutral(
        clamp_affinity(float(getattr(row, "affinity", 0.0) or 0.0)),
        int(row.updated_at or 0),
        daily_step=float(getattr(c, "llm_relationship_affinity_daily_decay_step", 0.02) or 0.02),
        now=now,
    )
    if (
        not content
        and warmth == 0.0
        and assertiveness == 0.0
        and affinity == 0.0
        and int(getattr(row, "rage", 0) or 0) == 0
        and int(getattr(row, "rage_silenced_until", 0) or 0) <= now
    ):
        return None
    return RelationshipProfile(
        content=content,
        warmth_delta=warmth,
        assertiveness_delta=assertiveness,
        affinity=affinity,
        source=str(row.source or "").strip() or "auto",
        weight=weight,
        rage=RageState(
            rage=max(0, min(100, int(getattr(row, "rage", 0) or 0))),
            last_attack_at=int(getattr(row, "rage_last_attack_at", 0) or 0),
            last_attack_message_id=int(getattr(row, "rage_last_attack_message_id", 0) or 0),
            silenced_until=int(getattr(row, "rage_silenced_until", 0) or 0),
            silence_reason=str(getattr(row, "rage_silence_reason", "") or ""),
        ),
    )


async def retrieve_relationship_note(
    bot_id: int,
    group_id: int | None,
    user_id: int,
    *,
    cfg: LlmConfig | None = None,
) -> str | None:
    """取当前对象的关系备注正文；无事实时返回 None（即使有语气偏置）。"""
    profile = await retrieve_relationship_profile(bot_id, group_id, user_id, cfg=cfg)
    if profile is None or not profile.has_facts:
        return None
    return profile.content


async def trim_relationship_notes(bot_id: int, group_id: int | None, *, cfg: LlmConfig | None = None) -> int:
    """惰性裁剪：删除衰减到阈值以下的过期关系备注，返回删除条数。"""
    if not is_relationship_store_available():
        return 0
    if _use_mongodb_backend():
        from pallas.product.llm.memory.relationship_store_mongo import trim_relationship_notes_mongo

        return await trim_relationship_notes_mongo(bot_id, group_id, cfg=cfg)
    if not _use_postgresql_backend():
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
    cfg: LlmConfig | None = None,
) -> list[dict[str, object]]:
    if not is_relationship_store_available():
        return []
    if _use_mongodb_backend():
        from pallas.product.llm.memory.relationship_store_mongo import list_relationship_notes_mongo

        return await list_relationship_notes_mongo(bot_id, group_id, query=query, limit=limit, cfg=cfg)
    if not _use_postgresql_backend():
        return []
    c = cfg or get_llm_config()
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
        user_hit = str(row.user_id or "").strip().casefold()
        if needle and needle not in content.casefold() and needle not in source.casefold() and needle not in user_hit:
            continue
        items.append({
            "id": int(row.id),
            "bot_id": int(row.bot_id),
            "group_id": int(row.group_id),
            "user_id": int(row.user_id),
            "content": content,
            "source": source,
            "weight": float(row.weight or 0.0),
            "warmth_delta": float(getattr(row, "warmth_delta", 0.0) or 0.0),
            "assertiveness_delta": float(getattr(row, "assertiveness_delta", 0.0) or 0.0),
            "affinity": decay_affinity_toward_neutral(
                float(getattr(row, "affinity", 0.0) or 0.0),
                int(row.updated_at or 0),
                daily_step=float(getattr(c, "llm_relationship_affinity_daily_decay_step", 0.02) or 0.02),
            ),
            "created_at": int(row.created_at or 0),
            "updated_at": int(row.updated_at or 0),
        })
        if len(items) >= max_limit:
            break
    return items


async def set_affinity(
    bot_id: int,
    group_id: int | None,
    user_id: int,
    affinity: float,
    *,
    cfg: LlmConfig | None = None,
) -> bool:
    """WebUI 覆盖：把 affinity 设绝对值；无档案时仅建 affinity 行。"""
    if not is_relationship_store_available() or not user_id:
        return False
    if _use_mongodb_backend():
        from pallas.product.llm.memory.relationship_store_mongo import set_affinity_mongo

        return await set_affinity_mongo(bot_id, group_id, user_id, affinity, cfg=cfg)
    if not _use_postgresql_backend():
        return False
    scope_gid = normalize_group_scope(group_id)
    now = int(time.time())
    value = clamp_affinity(float(affinity))
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
            existing.affinity = value
            existing.updated_at = now
        else:
            session.add(
                LlmRelationshipNoteRow(
                    bot_id=int(bot_id),
                    group_id=scope_gid,
                    user_id=int(user_id),
                    content="",
                    source="auto",
                    weight=1.0,
                    affinity=value,
                    created_at=now,
                    updated_at=now,
                )
            )
        await session.commit()
    return True


async def delete_relationship_note(note_id: int, *, bot_id: int | None = None) -> bool:
    if not is_relationship_store_available():
        return False
    if _use_mongodb_backend():
        from pallas.product.llm.memory.relationship_store_mongo import delete_relationship_note_mongo

        return await delete_relationship_note_mongo(note_id, bot_id=bot_id)
    if not _use_postgresql_backend():
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
