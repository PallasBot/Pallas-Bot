from __future__ import annotations

from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

if TYPE_CHECKING:
    from pallas.core.foundation.db.modules import (
        AdminMember,
        Answer,
        Ban,
        BlackList,
        Context,
        ImageCache,
        Message,
        PallasACL,
    )


@runtime_checkable
class AclDecisionLike(Protocol):
    allow: bool
    priority: int
    source: str


@runtime_checkable
class ContextRepository(Protocol):
    async def find_by_keywords(self, keywords: str) -> Context | None:
        """根据 keywords 查找 Context 文档"""
        ...

    async def context_exists_by_keywords(self, keywords: str) -> bool:
        """keywords 是否存在，避免全量加载。"""
        ...

    async def save(self, context: Context) -> None:
        """覆盖写 Context；新业务优先细粒度 API。"""
        ...

    async def insert(self, context: Context) -> None:
        """插入新的 Context 文档"""
        ...

    async def delete_expired(self, expiration: int, threshold: int) -> None:
        """删除过期且 trigger_count 低于阈值的 Context 文档"""
        ...

    async def find_for_cleanup(self, trigger_threshold: int, expiration: int) -> list[Context]:
        """查找需要清理的 Context 文档"""
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
        """原子 upsert Answer 并递增 Context.trigger_count；Context 须已存在。"""
        ...

    async def replace_answers(self, keywords: str, answers: list[Answer], clear_time: int) -> None:
        """替换 Context.answers 并更新 clear_time。"""
        ...

    async def append_ban(self, keywords: str, ban: Ban) -> None:
        """追加 Ban；Context 不存在则 no-op。"""
        ...

    async def find_ban_reply_target(self, group_id: int, reply_message: str) -> tuple[str, str] | None:
        """按群号与 reply 原文反查 pre/reply keywords。"""
        ...

    async def list_answers_for_group_since(self, group_id: int, cutoff_time: int) -> list[Answer]:
        """列出指定群在 cutoff_time 之后的 Answer 样本，供画像/统计使用。"""
        ...


class ContextRepositoryExistenceMixin:
    """为已有 find_by_keywords 的仓储提供 exists 默认实现。"""

    async def context_exists_by_keywords(self, keywords: str) -> bool:
        return (await self.find_by_keywords(keywords)) is not None


@runtime_checkable
class MessageRepository(Protocol):
    async def bulk_insert(self, messages: list[Message]) -> None:
        """批量插入 Message 文档"""
        ...

    async def find_recent_in_group(
        self,
        group_id: int,
        *,
        before_time: int | None = None,
        user_id: int | None = None,
        limit: int = 8,
    ) -> list[Message]:
        """群内近期消息，按 time 升序。"""
        ...

    async def list_recent_group_ids_for_bot(
        self,
        bot_id: int,
        *,
        since_time: int,
        limit: int = 128,
    ) -> list[int]:
        """since_time 后有发言的群号列表。"""
        ...

    async def list_recent_bot_ids_for_group(
        self,
        group_id: int,
        *,
        since_time: int,
        limit: int = 32,
    ) -> list[int]:
        """since_time 后有发言的 bot 列表。"""
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
    通用配置 Repository。
    供 BotConfig / GroupConfig / UserConfig / help plugin_manager 使用。
    """

    async def get(self, key_id: int, *, ignore_cache: bool = False) -> Any | None:
        """根据主键 id 获取配置文档，返回 None 表示不存在。"""
        ...

    async def get_or_create(self, key_id: int, **defaults: Any) -> tuple[Any, bool]:
        """
        获取配置文档，若不存在则用 defaults 创建新文档。
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
        失效 Repository 级缓存。
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
        """保存/更新图片缓存"""
        ...

    async def delete_old(self, before_date: int) -> None:
        """按 date 删除早于指定日期的记录"""
        ...

    async def delete_low_ref(self, ref_threshold: int) -> None:
        """删除 ref_times 低于阈值的记录"""
        ...


@runtime_checkable
class AdminRepository(Protocol):
    """管理员身份表：判断「谁是管理员」用，权限细节由 ACL 表表达。"""

    async def is_admin(self, user_id: int, *, bot_id: int | None = None) -> bool:
        """scope=all 时跨 bot 全平台；scope=bot 且 bot_id 匹配时本地；其他场景返回 False。"""
        ...

    async def upsert_member(
        self,
        *,
        user_id: int,
        scope: str,
        bot_id: int | None = None,
        note: str | None = None,
    ) -> AdminMember:
        """新增或更新一个 AdminMember 行，返回最新文档。"""
        ...

    async def remove_member(
        self,
        *,
        user_id: int,
        scope: str,
        bot_id: int | None = None,
    ) -> int:
        """删除匹配行，返回被删除的行数。"""
        ...

    async def delete_member(self, member_id: Any) -> int:
        """按主键直接删除。Mongo 后端须接受 str(ObjectId)。"""
        ...

    async def list_members(
        self,
        *,
        scope: str | None = None,
        bot_id: int | None = None,
    ) -> list[AdminMember]:
        """按 scope/bot_id 过滤列出成员。"""
        ...

    async def list_admin_user_ids(self, *, bot_id: int | None) -> list[int]:
        """只查 (bot_id 或 scope=all) 的 user_id 列表，给 acl_admin_bypass 做库侧过滤用。"""
        ...


@runtime_checkable
class AclRepository(Protocol):
    """ACL 规则表：负责 ACL 规则的 CRUD。"""

    async def list_rules(
        self,
        *,
        action: str | None = None,
        target: str | None = None,
        role: str | None = None,
        subject: str | None = None,
    ) -> list[PallasACL]:
        """按可选过滤列出规则。"""
        ...

    async def list_all(self) -> list[PallasACL]:
        ...

    async def list_matching_rules(
        self,
        *,
        action: str,
        target: str | None = None,
    ) -> list[PallasACL]:
        """按 action 必填、target 可选（target 在表里允许 "*" 通配）下推到库侧过滤，
        主要给 ACL 引擎 fast-path 使用。返回的规则仍需引擎层做 role/subject 二级匹配。
        """
        ...

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
    ) -> PallasACL:
        """按 (role, subject, action, target_scope, target) 唯一键 upsert。"""
        ...

    async def delete_rule(self, rule_id: Any) -> int:
        """按主键删除；Mongo 端 ``rule_id`` 是 ``str(ObjectId)``。"""
        ...

    async def delete_by_signature(
        self,
        *,
        role: str,
        subject: str | None,
        action: str,
        target_scope: str,
        target: str,
    ) -> int:
        """按唯一键删除，返回被删行数。用于 unban 等动作。"""
        ...

    async def list_group_block_targets(self) -> set[str]:
        """返回 ``target='group:<gid>'`` 的 target 集合，用于 ban_gate stale 清理。"""
        ...

    async def has_run_step(self, step: str) -> bool:
        """SchemaMigration 步骤幂等登记。"""
        ...

    async def mark_run_step(self, step: str) -> None:
        """登记一个 schema_migration 步骤，幂等。"""
        ...
