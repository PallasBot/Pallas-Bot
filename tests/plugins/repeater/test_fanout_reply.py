import pytest
from nonebot.adapters.onebot.v11 import ActionFailed, Message

from packages.repeater import fanout_reply
from packages.repeater.responder import ReplyBundle, Responder


@pytest.mark.asyncio
async def test_dispatch_repeater_fanout_payload_schedules_local_and_remote_bots(monkeypatch):
    scheduled: list[str | None] = []

    def fake_create_task(coro, *, name=None):
        scheduled.append(name)
        coro.close()
        return object()

    monkeypatch.setattr(fanout_reply.asyncio, "create_task", fake_create_task)
    monkeypatch.setattr(
        "pallas.core.platform.shard.presence.bot_has_cluster_connection",
        lambda bot_id: bot_id in {10, 20},
    )
    monkeypatch.setattr(
        "pallas.core.platform.shard.presence.bot_has_local_connection",
        lambda bot_id: bot_id == 10,
    )
    monkeypatch.setattr(fanout_reply.shard_ctx, "sharding_active", lambda: True)

    await fanout_reply.dispatch_repeater_fanout_payload(
        [10, 20],
        {"group_id": 3, "fanout_bot_ids": [10, 20]},
    )

    assert scheduled == ["repeater_fanout_10_3", "repeater_fanout_remote_batch_3"]


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


@pytest.mark.asyncio
async def test_send_repeater_answers_forgets_bot_removed_from_group(monkeypatch):
    import packages.repeater as repeater
    from pallas.core.platform.multi_bot import group_online_cache

    group_id = 626266906
    bot_id = 111

    class FakeConfig:
        async def refresh_cooldown(self, _key: str) -> None:
            return None

        async def security(self) -> bool:
            return False

    class FakeBot:
        async def send_group_msg(self, **_kwargs):
            raise ActionFailed(retcode=100, message="发送失败，你已被移出该群，请重新加群。")

    async def answers():
        yield "reply"

    async def post_proc(item, *_args):
        return item

    async def no_sleep(_delay):
        return None

    group_online_cache.clear_group_online_cache()
    group_online_cache.remember_local_group_bot(group_id, bot_id)
    fanout_reply._FANOUT_BOT_IDS_CACHE[group_id] = (float("inf"), [bot_id, 222])
    monkeypatch.setattr(fanout_reply, "BotConfig", lambda *_args, **_kwargs: FakeConfig())
    monkeypatch.setattr(fanout_reply, "get_bot", lambda _bot_id: FakeBot())
    monkeypatch.setattr(fanout_reply.asyncio, "sleep", no_sleep)
    monkeypatch.setattr(repeater, "post_proc", post_proc)

    try:
        await fanout_reply.send_repeater_answers(bot_id, group_id, answers(), fanout=True)

        assert group_online_cache.recent_local_group_bot_ids(group_id) == []
        assert group_id not in fanout_reply._FANOUT_BOT_IDS_CACHE
    finally:
        group_online_cache.clear_group_online_cache()
        fanout_reply._FANOUT_BOT_IDS_CACHE.clear()


@pytest.mark.asyncio
async def test_send_repeater_answers_skips_empty_post_processed_message(monkeypatch):
    import packages.repeater as repeater

    class FakeConfig:
        async def refresh_cooldown(self, _key: str) -> None:
            return None

    class FakeBot:
        calls = 0

        async def send_group_msg(self, **_kwargs):
            self.calls += 1

    async def answers():
        yield "expired image"

    async def empty_post_proc(*_args):
        return Message()

    async def no_sleep(_delay):
        return None

    bot = FakeBot()
    monkeypatch.setattr(fanout_reply, "BotConfig", lambda *_args, **_kwargs: FakeConfig())
    monkeypatch.setattr(fanout_reply, "get_bot", lambda _bot_id: bot)
    monkeypatch.setattr(fanout_reply.asyncio, "sleep", no_sleep)
    monkeypatch.setattr(repeater, "post_proc", empty_post_proc)

    await fanout_reply.send_repeater_answers(111, 222, answers())

    assert bot.calls == 0


@pytest.mark.asyncio
async def test_send_repeater_answers_records_corpus_route_once(monkeypatch):
    import packages.repeater as repeater
    from packages.repeater import sticker_followup
    from pallas.product.llm.task_metrics import clear_llm_task_metrics_for_tests, llm_task_metrics_snapshot

    class FakeConfig:
        async def refresh_cooldown(self, _key: str) -> None:
            return None

    class FakeBot:
        calls = 0

        async def send_group_msg(self, **_kwargs):
            self.calls += 1

    async def answers():
        yield "first"
        yield "second"

    async def pass_proc(item, *_args):
        return item

    async def no_sleep(_delay):
        return None

    async def no_sticker_followup(*_args, **_kwargs):
        return False

    bot = FakeBot()
    monkeypatch.setattr(fanout_reply, "BotConfig", lambda *_args, **_kwargs: FakeConfig())
    monkeypatch.setattr(fanout_reply, "get_bot", lambda _bot_id: bot)
    monkeypatch.setattr(fanout_reply.asyncio, "sleep", no_sleep)
    monkeypatch.setattr(repeater, "post_proc", pass_proc)
    monkeypatch.setattr(sticker_followup, "maybe_send_repeater_sticker_followup", no_sticker_followup)

    clear_llm_task_metrics_for_tests()
    try:
        await fanout_reply.send_repeater_answers(111, 222, answers())
        assert bot.calls == 2
        snap = llm_task_metrics_snapshot()
        assert snap["by_task"]["other"]["route_counts"] == {"corpus_select": 1}
    finally:
        clear_llm_task_metrics_for_tests()
