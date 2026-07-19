"""MongoDB 版 Repository 协议接口实现"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from beanie.operators import Or

from pallas.core.foundation.db.modules import (
    AdminMember,
    Answer,
    Ban,
    BlackList,
    Context,
    ImageCache,
    Message,
    PallasACL,
    SchemaMigration,
)
from pallas.core.shared.utils.invalidate_cache import clear_model_cache

if TYPE_CHECKING:
    from beanie import Document


class MongoContextRepository:
    """MongoDB 版 ContextRepository 实现"""

    async def context_exists_by_keywords(self, keywords: str) -> bool:
        coll = Context.get_pymongo_collection()
        doc = await coll.find_one({"keywords": keywords}, projection={"_id": 1})
        return doc is not None

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
        from pallas.product.llm.corpus_contamination import reject_corpus_learn_message

        if reject_corpus_learn_message(message, source="mongo_upsert_answer"):
            return
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

    async def find_ban_reply_target(self, group_id: int, reply_message: str) -> tuple[str, str] | None:
        collection = Context.get_pymongo_collection()
        pipeline = [
            {"$match": {"answers": {"$elemMatch": {"group_id": int(group_id), "messages": str(reply_message)}}}},
            {"$unwind": "$answers"},
            {"$match": {"answers.group_id": int(group_id), "answers.messages": str(reply_message)}},
            {"$sort": {"answers.time": -1}},
            {"$limit": 1},
            {"$project": {"_id": 0, "keywords": 1, "reply_keywords": "$answers.keywords"}},
        ]
        docs = await collection.aggregate(pipeline).to_list(length=1)
        if not docs:
            return None
        doc = docs[0]
        return str(doc.get("keywords") or ""), str(doc.get("reply_keywords") or "")

    async def list_answers_for_group_since(self, group_id: int, cutoff_time: int) -> list[Answer]:
        contexts = await Context.find({"answers.group_id": int(group_id)}).to_list()
        out: list[Answer] = []
        for context in contexts:
            out.extend(
                answer
                for answer in context.answers
                if int(answer.group_id) == int(group_id) and int(answer.time) >= int(cutoff_time)
            )
        return out


class MongoMessageRepository:
    """MongoDB 版 MessageRepository 实现"""

    async def find_recent_in_group(
        self,
        group_id: int,
        *,
        before_time: int | None = None,
        user_id: int | None = None,
        limit: int = 8,
    ) -> list[Message]:
        cap = max(1, min(int(limit), 32))
        query: dict = {"group_id": int(group_id)}
        if before_time is not None:
            query["time"] = {"$lt": int(before_time)}
        if user_id is not None:
            query["user_id"] = int(user_id)
        docs = await Message.find(query).sort("-time").limit(cap).to_list()
        docs.reverse()
        return docs

    async def list_recent_group_ids_for_bot(
        self,
        bot_id: int,
        *,
        since_time: int,
        limit: int = 128,
    ) -> list[int]:
        cap = max(1, min(int(limit), 512))
        pipeline = [
            {"$match": {"bot_id": int(bot_id), "time": {"$gte": int(since_time)}}},
            {"$group": {"_id": "$group_id"}},
            {"$sort": {"_id": 1}},
            {"$limit": cap},
        ]
        rows = await Message.aggregate(pipeline).to_list()
        return [int(row["_id"]) for row in rows]

    async def list_recent_bot_ids_for_group(
        self,
        group_id: int,
        *,
        since_time: int,
        limit: int = 32,
    ) -> list[int]:
        cap = max(1, min(int(limit), 128))
        pipeline = [
            {"$match": {"group_id": int(group_id), "time": {"$gte": int(since_time)}}},
            {"$group": {"_id": "$bot_id"}},
            {"$sort": {"_id": 1}},
            {"$limit": cap},
        ]
        rows = await Message.aggregate(pipeline).to_list()
        return [int(row["_id"]) for row in rows]

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
    MongoDB 版 ConfigRepository 实现。

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


class MongoAdminRepository:
    """MongoDB 版 AdminRepository。"""

    async def is_admin(self, user_id: int, *, bot_id: int | None = None) -> bool:
        if bot_id is not None:
            hit = await AdminMember.find_one({"scope": "bot", "bot_id": int(bot_id), "user_id": int(user_id)})
            if hit is not None:
                return True
        # scope=all 全平台
        hit = await AdminMember.find_one({"scope": "all", "user_id": int(user_id)})
        return hit is not None

    async def upsert_member(
        self,
        *,
        user_id: int,
        scope: str,
        bot_id: int | None = None,
        note: str | None = None,
    ) -> AdminMember:
        now = int(__import__("time").time())
        scope_norm = "bot" if scope not in ("bot", "all") else scope
        bot_id_norm = int(bot_id) if scope_norm == "bot" and bot_id is not None else None
        query = {"scope": scope_norm, "bot_id": bot_id_norm, "user_id": int(user_id)}
        doc = await AdminMember.find_one(query)
        if doc is None:
            doc = AdminMember(
                scope=scope_norm,
                bot_id=bot_id_norm,
                user_id=int(user_id),
                note=note,
                created_at=now,
                updated_at=now,
            )
            await doc.insert()
            return doc
        set_fields: dict[str, Any] = {"updated_at": now}
        if note is not None:
            set_fields["note"] = note
        await doc.set(set_fields)
        return doc

    async def remove_member(
        self,
        *,
        user_id: int,
        scope: str,
        bot_id: int | None = None,
    ) -> int:
        scope_norm = "bot" if scope not in ("bot", "all") else scope
        bot_id_norm = int(bot_id) if scope_norm == "bot" and bot_id is not None else None
        result = await AdminMember.find({"scope": scope_norm, "bot_id": bot_id_norm, "user_id": int(user_id)}).delete()
        return int(getattr(result, "deleted_count", 0) or 0)

    async def delete_member(self, member_id: Any) -> int:
        from beanie import PydanticObjectId

        try:
            oid = PydanticObjectId(str(member_id))
        except Exception:
            return 0
        doc = await AdminMember.get(oid)
        if doc is None:
            return 0
        await doc.delete()
        return 1

    async def list_members(
        self,
        *,
        scope: str | None = None,
        bot_id: int | None = None,
    ) -> list[AdminMember]:
        query: dict[str, Any] = {}
        if scope is not None:
            query["scope"] = scope
        if bot_id is not None:
            query["bot_id"] = int(bot_id)
        return await AdminMember.find(query).to_list()

    async def has_user(self, user_id: int) -> bool:
        hit = await AdminMember.find_one({"user_id": int(user_id)})
        return hit is not None

    async def list_admin_user_ids(self, *, bot_id: int | None) -> list[int]:
        # scope=all 或 (scope=bot 且 bot_id 匹配)；bot_id 为 None 时仅 scope=all
        if bot_id is None:
            query: dict[str, Any] = {"scope": "all"}
        else:
            query = {
                "$or": [
                    {"scope": "all"},
                    {"scope": "bot", "bot_id": int(bot_id)},
                ],
            }
        coll = AdminMember.get_pymongo_collection()
        cursor = coll.find(query, projection={"user_id": 1, "_id": 0})
        out: list[int] = []
        async for doc in cursor:
            uid = doc.get("user_id")
            if uid is not None:
                try:
                    out.append(int(uid))
                except Exception:
                    continue
        return out


class MongoAclRepository:
    """MongoDB 版 AclRepository。"""

    @staticmethod
    def _match_query(
        *,
        action: str | None = None,
        target: str | None = None,
        role: str | None = None,
        subject: str | None = None,
    ) -> dict[str, Any]:
        query: dict[str, Any] = {}
        if action is not None:
            query["action"] = action
        if target is not None:
            query["target"] = target
        if role is not None:
            query["role"] = role
        if subject is not None:
            query["subject"] = subject
        return query

    async def list_rules(
        self,
        *,
        action: str | None = None,
        target: str | None = None,
        role: str | None = None,
        subject: str | None = None,
    ) -> list[PallasACL]:
        q = self._match_query(action=action, target=target, role=role, subject=subject)
        return await PallasACL.find(q).to_list()

    async def list_all(self) -> list[PallasACL]:
        return await PallasACL.find_all().to_list()

    async def list_matching_rules(
        self,
        *,
        action: str,
        target: str | None = None,
    ) -> list[PallasACL]:
        # 库侧过滤：action 必填；target 为 None 时退化为 $or(target==*, target==target_value)
        # 仍接受 target==通配与 target==specific 同时存在的高频查询。
        query: dict[str, Any] = {"action": action}
        if target is not None:
            query["$or"] = [{"target": "*"}, {"target": target}]
        return await PallasACL.find(query).to_list()

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
        now = int(__import__("time").time())
        query = {
            "role": role,
            "subject": subject,
            "action": action,
            "target_scope": target_scope,
            "target": target,
        }
        doc = await PallasACL.find_one(query)
        if doc is None:
            doc = PallasACL(
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
            await doc.insert()
            return doc
        await doc.set({
            "effect": effect,
            "priority": int(priority),
            "source": source,
            "updated_at": now,
        })
        return doc

    async def delete_rule(self, rule_id: Any) -> int:
        from beanie import PydanticObjectId

        try:
            oid = PydanticObjectId(str(rule_id))
        except Exception:
            return 0
        doc = await PallasACL.get(oid)
        if doc is None:
            return 0
        await doc.delete()
        return 1

    async def delete_by_signature(
        self,
        *,
        role: str,
        subject: str | None,
        action: str,
        target_scope: str,
        target: str,
    ) -> int:
        result = await PallasACL.find({
            "role": role,
            "subject": subject,
            "action": action,
            "target_scope": target_scope,
            "target": target,
        }).delete()
        return int(getattr(result, "deleted_count", 0) or 0)

    async def list_group_block_targets(self) -> set[str]:
        """只返回 ``target='group:<gid>'`` 的字符串集合。"""
        out: set[str] = set()
        docs = await PallasACL.find({"target": {"$regex": "^group:"}}).to_list()
        for d in docs:
            t = getattr(d, "target", "")
            if t:
                out.add(t)
        return out

    async def has_run_step(self, step: str) -> bool:
        return (await SchemaMigration.find_one({"step": step})) is not None

    async def mark_run_step(self, step: str) -> None:
        from pallas.core.foundation.db.modules import SchemaMigration as _Sm

        existing = await _Sm.find_one({"step": step})
        if existing is not None:
            return
        await _Sm(step=step).insert()
