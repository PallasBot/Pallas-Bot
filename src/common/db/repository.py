from __future__ import annotations

from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

if TYPE_CHECKING:
    from src.common.db.modules import Answer, Ban, BlackList, Context, ImageCache, Message


@runtime_checkable
class ContextRepository(Protocol):
    async def find_by_keywords(self, keywords: str) -> Context | None:
        """根据 keywords 查找 Context 文档"""
        ...

    async def save(self, context: Context) -> None:
        """保存/更新已有的 Context 文档（整文档覆盖写）

        注意：新业务代码优先使用 upsert_answer / replace_answers / append_ban 等
        细粒度 API；本方法保留用于未抽象出的特殊场景。
        """
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

    async def upsert_answer(
        self,
        keywords: str,
        group_id: int,
        answer_keywords: str,
        answer_time: int,
        message: str,
        append_on_existing: bool,
    ) -> None:
        """
        原子 upsert 一条 Answer：
        - 若 Context(keywords=keywords) 下已存在 (group_id, answer_keywords) 的 Answer，
          则 count += 1、time=answer_time；当 append_on_existing=True 时额外把
          message 追加到该 Answer 的 messages 列表
        - 否则新建一条 Answer(count=1, time=answer_time, messages=[message])
        - 同时 Context.trigger_count += 1，Context.time=answer_time

        要求实现具备并发原子性（Mongo 可用 $inc/$push + positional 更新；PG 用事务 + upsert）。
        前置条件：Context(keywords=keywords) 必须已存在，否则行为未定义 —— 调用方
        应先 find_by_keywords，不存在时走 insert(Context(...)) 路径。
        """
        ...

    async def replace_answers(self, keywords: str, answers: list[Answer], clear_time: int) -> None:
        """
        将指定 Context 的 answers 替换为给定列表，并更新 clear_time。
        用于 clearup_context 的周期性清理。
        """
        ...

    async def append_ban(self, keywords: str, ban: Ban) -> None:
        """
        向指定 Context 的 ban 列表追加一条 Ban 记录。
        若 Context(keywords=keywords) 不存在，则应为 no-op。
        """
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


@runtime_checkable
class ConfigRepository(Protocol):
    """
    通用配置 Repository（绑定到单一 Document/表）。
    供 BotConfig / GroupConfig / UserConfig / help plugin_manager 使用。
    """

    async def get(self, key_id: int, *, ignore_cache: bool = False) -> Any | None:
        """根据主键 id 获取配置文档，返回 None 表示不存在。"""
        ...

    async def get_or_create(self, key_id: int, **defaults: Any) -> tuple[Any, bool]:
        """
        获取配置文档，若不存在则用 defaults 创建新文档（primary_key 由 repo 自动注入）。
        返回 (document, created)。
        """
        ...

    async def upsert_field(self, key_id: int, field: str, value: Any) -> None:
        """
        更新/插入指定主键文档的单个字段。不存在则新建文档。
        不做 diff，直接 $set。
        """
        ...

    async def upsert_fields(self, key_id: int, fields: dict[str, Any]) -> None:
        """
        批量更新/插入多个字段，一次原子 $set。不存在则新建文档。
        """
        ...

    async def invalidate_cache(self) -> None:
        """
        失效 Repository 级缓存（仅部分实现有意义，如 Beanie 的 model-level cache）。
        默认实现为空。
        """
        ...


@runtime_checkable
class ImageCacheRepository(Protocol):
    async def find_by_cq_code(self, cq_code: str) -> ImageCache | None:
        """根据 CQ code 查找图片缓存"""
        ...

    async def insert(self, cache: ImageCache) -> None:
        """插入新的图片缓存"""
        ...

    async def save(self, cache: ImageCache) -> None:
        """保存/更新图片缓存（通常是 ref_times 变更）"""
        ...

    async def delete_old(self, before_date: int) -> None:
        """按 date 删除早于指定日期的记录"""
        ...

    async def delete_low_ref(self, ref_threshold: int) -> None:
        """删除 ref_times 低于阈值的记录"""
        ...
