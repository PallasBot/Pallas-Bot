"""黑名单操作历史的跨数据库写入。"""

from __future__ import annotations

import time

from nonebot import logger

from .runtime import get_db_backend


async def record_blacklist_audit(
    *,
    target_type: str,
    target_id: int,
    action: str,
    operator: str,
    reason: str = "",
    group_id: int | None = None,
    created_at: int | None = None,
) -> None:
    """追加一条黑名单操作历史。"""
    try:
        timestamp = int(time.time()) if created_at is None else int(created_at)
        data = {
            "target_type": str(target_type),
            "target_id": int(target_id),
            "group_id": int(group_id) if group_id is not None else None,
            "action": str(action),
            "reason": str(reason or ""),
            "operator": str(operator or ""),
            "created_at": timestamp,
        }
        backend = get_db_backend()
        if backend == "mongodb":
            from .modules import BlacklistAudit

            await BlacklistAudit(**data).insert()
            return
        if backend == "postgresql":
            from .repository_pg import BlacklistAuditRow, get_session

            async with get_session() as session:
                session.add(BlacklistAuditRow(**data))
                await session.commit()
            return
        raise ValueError(f"不支持的 DB 后端: {backend}")
    except Exception as exc:
        logger.warning(
            "黑名单状态已更新，但审计记录写入失败，target [{}:{}]、action [{}]：{}",
            target_type,
            target_id,
            action,
            exc,
        )
