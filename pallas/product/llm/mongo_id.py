from __future__ import annotations

from typing import TYPE_CHECKING

from pymongo import ReturnDocument

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable


async def allocate_mongo_int_id(
    counter_name: str,
    *,
    peek_max: Callable[[], Awaitable[int]],
) -> int:
    """原子分配单调递增 int ID（计数器集合 + 与现有 max 对齐）。

    用 ``llm_id_counter`` 文档 ``$inc``，插入前 ``$max`` 对齐业务表当前最大值，
    避免空库从 1 起步撞上已有数据，也避免并发 max+1 竞态。
    """
    from pallas.core.foundation.db.modules import LlmChatMessage

    db = LlmChatMessage.get_pymongo_collection().database
    coll = db["llm_id_counter"]
    current_max = max(0, int(await peek_max()))
    await coll.update_one({"_id": counter_name}, {"$max": {"seq": current_max}}, upsert=True)
    doc = await coll.find_one_and_update(
        {"_id": counter_name},
        {"$inc": {"seq": 1}},
        upsert=True,
        return_document=ReturnDocument.AFTER,
    )
    if not doc or doc.get("seq") is None:
        raise RuntimeError(f"mongo id counter unavailable: {counter_name}")
    return int(doc["seq"])
