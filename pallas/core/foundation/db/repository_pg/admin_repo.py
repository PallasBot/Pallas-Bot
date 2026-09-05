"""PostgreSQL Admin / ACL Repository"""

from __future__ import annotations

import time
from typing import Any

from sqlalchemy import and_, delete, or_, select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from pallas.core.foundation.db import repository_pg as _repo
from pallas.core.foundation.db.repository_pg.schema import AdminMemberRow, PallasACLRow, SchemaMigrationRow


def row_to_admin_member(row: AdminMemberRow):
    from pallas.core.foundation.db.modules import AdminMember

    return AdminMember.model_construct(
        id=row.id,
        scope=row.scope,
        bot_id=row.bot_id,
        user_id=row.user_id,
        note=row.note,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def row_to_pallas_acl(row: PallasACLRow):
    from pallas.core.foundation.db.modules import PallasACL

    return PallasACL.model_construct(
        id=row.id,
        role=row.role,
        subject=row.subject,
        action=row.action,
        target_scope=row.target_scope,
        target=row.target,
        effect=row.effect,
        priority=row.priority,
        source=row.source,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


class PgAdminRepository:
    """PG 版 AdminRepository。"""

    async def is_admin(self, user_id: int, *, bot_id: int | None = None) -> bool:
        async with _repo.get_session(read_only=True) as session:
            stmt = select(AdminMemberRow.id).where(AdminMemberRow.user_id == int(user_id))
            if bot_id is not None:
                stmt = stmt.where(
                    or_(
                        AdminMemberRow.scope == "bot",
                        AdminMemberRow.scope == "all",
                    )
                ).where(
                    or_(
                        AdminMemberRow.scope == "all",
                        AdminMemberRow.bot_id == int(bot_id),
                    )
                )
            else:
                stmt = stmt.where(AdminMemberRow.scope == "all")
            row = (await session.execute(stmt.limit(1))).scalar_one_or_none()
            return row is not None

    async def upsert_member(
        self,
        *,
        user_id: int,
        scope: str,
        bot_id: int | None = None,
        note: str | None = None,
    ) -> Any:
        now = int(time.time())
        scope_norm = "bot" if scope not in ("bot", "all") else scope
        bot_id_norm = int(bot_id) if scope_norm == "bot" and bot_id is not None else None
        async with _repo.get_session() as session:
            stmt = pg_insert(AdminMemberRow).values(
                scope=scope_norm,
                bot_id=bot_id_norm,
                user_id=int(user_id),
                note=note,
                created_at=now,
                updated_at=now,
            )
            stmt = stmt.on_conflict_do_update(
                index_elements=["scope", "bot_id", "user_id"],
                set_={
                    "updated_at": stmt.excluded.updated_at,
                    "note": stmt.excluded.note,
                },
            )
            row = (await session.execute(stmt.returning(AdminMemberRow))).scalar_one()
            await session.commit()
            return row_to_admin_member(row)

    async def remove_member(
        self,
        *,
        user_id: int,
        scope: str,
        bot_id: int | None = None,
    ) -> int:
        scope_norm = "bot" if scope not in ("bot", "all") else scope
        bot_id_norm = int(bot_id) if scope_norm == "bot" and bot_id is not None else None
        async with _repo.get_session() as session:
            result = await session.execute(
                delete(AdminMemberRow).where(
                    AdminMemberRow.scope == scope_norm,
                    AdminMemberRow.bot_id == bot_id_norm,
                    AdminMemberRow.user_id == int(user_id),
                )
            )
            await session.commit()
            return int(result.rowcount or 0)

    async def delete_member(self, member_id: Any) -> int:
        try:
            rid = int(member_id)
        except (TypeError, ValueError):
            return 0
        async with _repo.get_session() as session:
            result = await session.execute(delete(AdminMemberRow).where(AdminMemberRow.id == rid))
            await session.commit()
            return int(result.rowcount or 0)

    async def list_members(
        self,
        *,
        scope: str | None = None,
        bot_id: int | None = None,
    ) -> list[Any]:
        async with _repo.get_session(read_only=True) as session:
            stmt = select(AdminMemberRow)
            if scope is not None:
                stmt = stmt.where(AdminMemberRow.scope == scope)
            if bot_id is not None:
                stmt = stmt.where(AdminMemberRow.bot_id == int(bot_id))
            rows = (await session.execute(stmt)).scalars().all()
            return [row_to_admin_member(r) for r in rows]

    async def has_user(self, user_id: int) -> bool:
        async with _repo.get_session(read_only=True) as session:
            stmt = select(AdminMemberRow.id).where(AdminMemberRow.user_id == int(user_id)).limit(1)
            row = (await session.execute(stmt)).scalar_one_or_none()
            return row is not None

    async def list_admin_user_ids(self, *, bot_id: int | None) -> list[int]:
        async with _repo.get_session(read_only=True) as session:
            if bot_id is None:
                stmt = select(AdminMemberRow.user_id).where(AdminMemberRow.scope == "all")
            else:
                stmt = select(AdminMemberRow.user_id).where(
                    or_(
                        AdminMemberRow.scope == "all",
                        and_(
                            AdminMemberRow.scope == "bot",
                            AdminMemberRow.bot_id == int(bot_id),
                        ),
                    )
                )
            rows = (await session.execute(stmt)).scalars().all()
            return [int(r) for r in rows if r is not None]


class PgAclRepository:
    """PG 版 AclRepository。"""

    async def list_rules(
        self,
        *,
        action: str | None = None,
        target: str | None = None,
        role: str | None = None,
        subject: str | None = None,
    ) -> list[Any]:
        async with _repo.get_session(read_only=True) as session:
            stmt = select(PallasACLRow)
            if action is not None:
                stmt = stmt.where(PallasACLRow.action == action)
            if target is not None:
                stmt = stmt.where(PallasACLRow.target == target)
            if role is not None:
                stmt = stmt.where(PallasACLRow.role == role)
            if subject is not None:
                stmt = stmt.where(PallasACLRow.subject == subject)
            rows = (await session.execute(stmt)).scalars().all()
            return [row_to_pallas_acl(r) for r in rows]

    async def list_all(self) -> list[Any]:
        async with _repo.get_session(read_only=True) as session:
            rows = (await session.execute(select(PallasACLRow))).scalars().all()
            return [row_to_pallas_acl(r) for r in rows]

    async def list_matching_rules(
        self,
        *,
        action: str,
        target: str | None = None,
    ) -> list[Any]:
        async with _repo.get_session(read_only=True) as session:
            stmt = select(PallasACLRow).where(PallasACLRow.action == action)
            if target is not None:
                stmt = stmt.where(
                    or_(
                        PallasACLRow.target == "*",
                        PallasACLRow.target == target,
                    )
                )
            rows = (await session.execute(stmt)).scalars().all()
            return [row_to_pallas_acl(r) for r in rows]

    async def upsert_rule(
        self,
        *,
        role: str,
        subject: str | None,
        action: str,
        target_scope: str,
        target: str,
        effect: str,
        priority: int,
        source: str,
    ) -> Any:
        now = int(time.time())
        async with _repo.get_session() as session:
            stmt = pg_insert(PallasACLRow).values(
                role=role,
                subject=subject,
                action=action,
                target_scope=target_scope,
                target=target,
                effect=effect,
                priority=int(priority),
                source=source,
                created_at=now,
                updated_at=now,
            )
            stmt = stmt.on_conflict_do_update(
                index_elements=[
                    "role",
                    "subject",
                    "action",
                    "target_scope",
                    "target",
                ],
                set_={
                    "effect": stmt.excluded.effect,
                    "priority": stmt.excluded.priority,
                    "source": stmt.excluded.source,
                    "updated_at": stmt.excluded.updated_at,
                },
            )
            row = (await session.execute(stmt.returning(PallasACLRow))).scalar_one()
            await session.commit()
            return row_to_pallas_acl(row)

    async def delete_rule(self, rule_id: Any) -> int:
        try:
            rid = int(rule_id)
        except (TypeError, ValueError):
            return 0
        async with _repo.get_session() as session:
            result = await session.execute(delete(PallasACLRow).where(PallasACLRow.id == rid))
            await session.commit()
            return int(result.rowcount or 0)

    async def delete_by_signature(
        self,
        *,
        role: str,
        subject: str | None,
        action: str,
        target_scope: str,
        target: str,
    ) -> int:
        async with _repo.get_session() as session:
            result = await session.execute(
                delete(PallasACLRow).where(
                    PallasACLRow.role == role,
                    PallasACLRow.subject == subject,
                    PallasACLRow.action == action,
                    PallasACLRow.target_scope == target_scope,
                    PallasACLRow.target == target,
                )
            )
            await session.commit()
            return int(result.rowcount or 0)

    async def list_group_block_targets(self) -> set[str]:
        async with _repo.get_session(read_only=True) as session:
            stmt = select(PallasACLRow.target).where(PallasACLRow.target.like("group:%"))
            rows = (await session.execute(stmt)).scalars().all()
            return {row for row in rows if row}

    async def has_run_step(self, step: str) -> bool:
        async with _repo.get_session(read_only=True) as session:
            row = (
                await session.execute(select(SchemaMigrationRow.id).where(SchemaMigrationRow.step == step).limit(1))
            ).scalar_one_or_none()
            return row is not None

    async def mark_run_step(self, step: str) -> None:
        now = int(time.time())
        async with _repo.get_session() as session:
            stmt = pg_insert(SchemaMigrationRow).values(step=step, applied_at=now)
            stmt = stmt.on_conflict_do_update(
                index_elements=["step"],
                set_={"applied_at": stmt.excluded.applied_at},
            )
            await session.execute(stmt)
            await session.commit()
