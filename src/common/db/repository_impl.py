"""MongoDB implementations of Repository Protocol interfaces."""

from beanie.operators import Or

from src.common.db.modules import BlackList, Context, Message


class MongoContextRepository:
    """MongoDB implementation of ContextRepository using beanie ODM."""

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


class MongoMessageRepository:
    """MongoDB implementation of MessageRepository using beanie ODM."""

    async def bulk_insert(self, messages: list[Message]) -> None:
        await Message.insert_many(messages)


class MongoBlackListRepository:
    """MongoDB implementation of BlackListRepository using beanie ODM."""

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
