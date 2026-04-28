"""MongoDB 版 Repository 协议接口实现"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from beanie.operators import Or

from src.common.db.modules import (
    Answer,
    Ban,
    BlackList,
    Context,
    ImageCache,
    Message,
)
from src.common.utils.invalidate_cache import clear_model_cache

if TYPE_CHECKING:
    from beanie import Document


class MongoContextRepository:
    """MongoDB 版 ContextRepository 实现"""

    async def find_by_keywords(self, keywords: str) -> Context | None:
        return await Context.find_one(Context.keywords == keywords)

    async def save(self, context: Context) -> None:
        await context.save()

    async def insert(self, context: Context) -> None:
        await context.insert()

    async def delete_expired(self, expiration: int, threshold: int) -> None:
        await Context.find(
            Context.time < expiration,
            Context.trigger_count < threshold,
        ).delete()

    async def find_for_cleanup(self, trigger_threshold: int, expiration: int) -> list[Context]:
        return await Context.find(
            Or(
                Context.trigger_count > trigger_threshold,
                Context.clear_time < expiration,
            )
        ).to_list()

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
        原子 upsert：
          - 命中 (group_id, answer_keywords) 时：$inc count / $set time，
            append_on_existing 时 $push message
          - 未命中时：$push 新 Answer；第二步 filter 使用
            $not $elemMatch 防止并发下两个 writer 同时 push 造成重复 answer
          - 若第二步因并发被抢先（matched_count == 0），回退到第一步重试
            increment，保证 count 精确累加
        """
        collection = Context.get_pymongo_collection()

        increment_filter: dict[str, Any] = {
            "keywords": keywords,
            "answers": {"$elemMatch": {"group_id": group_id, "keywords": answer_keywords}},
        }
        increment_update: dict[str, Any] = {
            "$inc": {"answers.$.count": 1, "count": 1},
            "$set": {"answers.$.time": answer_time, "time": answer_time},
        }
        if append_on_existing:
            increment_update["$push"] = {"answers.$.messages": message}

        result = await collection.update_one(increment_filter, increment_update)
        if result.matched_count:
            return

        new_answer = Answer(
            keywords=answer_keywords,
            group_id=group_id,
            count=1,
            time=answer_time,
            messages=[message],
        ).model_dump(by_alias=True)

        push_result = await collection.update_one(
            {
                "keywords": keywords,
                "answers": {
                    "$not": {"$elemMatch": {"group_id": group_id, "keywords": answer_keywords}},
                },
            },
            {
                "$push": {"answers": new_answer},
                "$inc": {"count": 1},
                "$set": {"time": answer_time},
            },
        )
        if push_result.matched_count:
            return

        # 并发下被其他 writer 抢先 push，此处 answer 已存在 —— 回退为 increment
        await collection.update_one(increment_filter, increment_update)

    async def replace_answers(self, keywords: str, answers: list[Answer], clear_time: int) -> None:
        collection = Context.get_pymongo_collection()
        serialized = [a.model_dump(by_alias=True) for a in answers]
        await collection.update_one(
            {"keywords": keywords},
            {"$set": {"answers": serialized, "clear_time": clear_time}},
        )

    async def append_ban(self, keywords: str, ban: Ban) -> None:
        collection = Context.get_pymongo_collection()
        await collection.update_one(
            {"keywords": keywords},
            {"$push": {"ban": ban.model_dump(by_alias=True)}},
        )


class MongoMessageRepository:
    """MongoDB 版 MessageRepository 实现"""

    async def bulk_insert(self, messages: list[Message]) -> None:
        await Message.insert_many(messages)


class MongoBlackListRepository:
    """MongoDB 版 BlackListRepository 实现"""

    async def find_all(self) -> list[BlackList]:
        return await BlackList.find_all().to_list()

    async def upsert_answers(self, group_id: int, answers: list[str]) -> None:
        await BlackList.find_one(BlackList.group_id == group_id).upsert(  # type: ignore[misc]
            {"$set": {"answers": answers}},
            on_insert=BlackList(group_id=group_id, answers=answers),
        )

    async def upsert_answers_reserve(self, group_id: int, answers: list[str]) -> None:
        await BlackList.find_one(BlackList.group_id == group_id).upsert(  # type: ignore[misc]
            {"$set": {"answers_reserve": answers}},
            on_insert=BlackList(group_id=group_id, answers_reserve=answers),
        )


class MongoConfigRepository:
    """
    MongoDB 版 ConfigRepository 实现（通用，绑定单一 Document + 主键字段）。

    用法：
        MongoConfigRepository(BotConfigModule, "account")
        MongoConfigRepository(GroupConfigModule, "group_id")
        MongoConfigRepository(UserConfigModule, "user_id")
    """

    def __init__(self, module_class: type[Document], primary_key: str) -> None:
        self._module_class = module_class
        self._primary_key = primary_key

    async def get(self, key_id: int, *, ignore_cache: bool = False) -> Any | None:
        # Beanie: ignore_cache 仅对 use_cache=True 的 Settings 生效，其余为 no-op
        return await self._module_class.find_one(
            {self._primary_key: key_id},
            ignore_cache=ignore_cache,
        )

    async def get_or_create(self, key_id: int, **defaults: Any) -> tuple[Any, bool]:
        existing = await self._module_class.find_one({self._primary_key: key_id})
        if existing is not None:
            return existing, False
        try:
            new_doc = self._module_class(**{self._primary_key: key_id, **defaults})
            await new_doc.insert()
            return new_doc, True
        except Exception:
            doc = await self._module_class.find_one({self._primary_key: key_id})
            return doc, False

    async def upsert_field(self, key_id: int, field: str, value: Any) -> None:
        collection = self._module_class.get_pymongo_collection()
        await collection.update_one(
            {self._primary_key: key_id},
            {"$set": {field: value}},
            upsert=True,
        )
        clear_model_cache(self._module_class)

    async def upsert_fields(self, key_id: int, fields: dict[str, Any]) -> None:
        """批量原子 $set 多个字段"""
        if not fields:
            return
        collection = self._module_class.get_pymongo_collection()
        await collection.update_one(
            {self._primary_key: key_id},
            {"$set": fields},
            upsert=True,
        )
        clear_model_cache(self._module_class)

    async def invalidate_cache(self) -> None:
        clear_model_cache(self._module_class)


class MongoImageCacheRepository:
    """MongoDB 版 ImageCacheRepository 实现"""

    async def find_by_cq_code(self, cq_code: str) -> ImageCache | None:
        return await ImageCache.find_one(ImageCache.cq_code == cq_code)

    async def insert(self, cache: ImageCache) -> None:
        await cache.insert()

    async def save(self, cache: ImageCache) -> None:
        await cache.save()

    async def delete_old(self, before_date: int) -> None:
        await ImageCache.find(ImageCache.date < before_date).delete()

    async def delete_low_ref(self, ref_threshold: int) -> None:
        await ImageCache.find(ImageCache.ref_times < ref_threshold).delete()
