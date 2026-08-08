import pytest

from packages.repeater import fanout_reply
from packages.repeater.responder import ReplyBundle, Responder


def test_select_fanout_bot_ids_picks_non_empty_random_subset(monkeypatch):
    monkeypatch.setattr(fanout_reply.random, "randint", lambda low, high: 2)
    monkeypatch.setattr(fanout_reply.random, "sample", lambda ids, count: [33, 11])

    assert fanout_reply.select_fanout_bot_ids([11, 22, 33], max_bots=3) == [11, 33]


def test_select_fanout_bot_ids_honors_zero_as_no_cap(monkeypatch):
    monkeypatch.setattr(fanout_reply.random, "randint", lambda low, high: high)
    monkeypatch.setattr(fanout_reply.random, "sample", lambda ids, count: list(ids))

    assert fanout_reply.select_fanout_bot_ids([11, 22, 33], max_bots=0) == [11, 22, 33]


def test_pick_fanout_plan_assigns_distinct_candidates_before_reuse(monkeypatch):
    bundle = ReplyBundle(
        answer_list=["fallback"],
        answer_keywords="key",
        message_pool=["one", "two", "three"],
    )
    monkeypatch.setattr(fanout_reply.random.Random, "shuffle", lambda _self, _items: None)

    peers = [10, 20, 30, 40]
    replies = [Responder.pick_fanout_plan(bundle, bot_id, peer_bot_ids=peers)[0][0] for bot_id in peers]

    assert replies == ["one", "two", "three", "one"]


@pytest.mark.asyncio
async def test_list_fanout_bot_ids_keeps_all_eligible_bots_for_random_selection(monkeypatch):
    fanout_reply._FANOUT_BOT_IDS_CACHE.clear()
    monkeypatch.setattr(fanout_reply, "get_repeater_config", lambda: type("C", (), {"fanout_max_bots": 2})())

    async def online_bot_ids(_group_id: int) -> list[int]:
        return [11, 22, 33]

    async def may_reply(_bot_id: int, _group_id: int) -> bool:
        return True

    monkeypatch.setattr(
        "pallas.core.platform.multi_bot.group_fleet_probe.list_group_online_bot_ids",
        online_bot_ids,
    )
    monkeypatch.setattr(fanout_reply, "bot_may_repeater_reply", may_reply)

    assert await fanout_reply.list_fanout_bot_ids(1) == [11, 22, 33]
