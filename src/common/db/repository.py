from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from src.common.db.modules import BlackList, Context, Message


@runtime_checkable
class ContextRepository(Protocol):
    async def find_by_keywords(self, keywords: str) -> Context | None:
        """根据 keywords 查找 Context 文档"""
        ...

    async def save(self, context: Context) -> None:
        """保存/更新已有的 Context 文档"""
        ...

    async def insert(self, context: Context) -> None:
        """插入新的 Context 文档"""
        ...

    async def delete_expired(self, expiration: int, threshold: int) -> None:
        """删除过期且 trigger_count 低于阈值的 Context 文档"""
        ...

    async def find_for_cleanup(self, trigger_threshold: int, expiration: int) -> list[Context]:
        """查找需要清理的 Context 文档（trigger_count 过高或 clear_time 过旧）"""
        ...


@runtime_checkable
class MessageRepository(Protocol):
    async def bulk_insert(self, messages: list[Message]) -> None:
        """批量插入 Message 文档"""
        ...


@runtime_checkable
class BlackListRepository(Protocol):
    async def find_all(self) -> list[BlackList]:
        """获取所有 BlackList 文档"""
        ...

    async def upsert_answers(self, group_id: int, answers: list[str]) -> None:
        """更新或插入指定群的 answers 黑名单"""
        ...

    async def upsert_answers_reserve(self, group_id: int, answers: list[str]) -> None:
        """更新或插入指定群的 answers_reserve 候选黑名单"""
        ...
