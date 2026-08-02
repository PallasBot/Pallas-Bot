from __future__ import annotations

from packages.repeater.responder import ReplyBundle, Responder


def test_pick_fanout_plan_differs_by_bot_id() -> None:
    bundle = ReplyBundle(
        answer_list=["同一句"],
        answer_keywords="kw",
        message_pool=["句子甲", "句子乙", "句子丙", "句子丁"],
    )
    peers = (10001, 10002, 10003, 10004)
    plans = {Responder.pick_fanout_plan(bundle, bot_id, peer_bot_ids=peers)[0][0] for bot_id in peers}
    assert len(plans) == 4


def test_pick_fanout_plan_unique_when_pool_covers_peers() -> None:
    bundle = ReplyBundle(
        answer_list=["同一句"],
        answer_keywords="hello",
        message_pool=["甲", "乙", "丙"],
    )
    peers = (11, 22, 33)
    chosen = [Responder.pick_fanout_plan(bundle, bid, peer_bot_ids=peers)[0][0] for bid in peers]
    assert len(set(chosen)) == 3
    assert set(chosen) <= {"甲", "乙", "丙"}


def test_pick_fanout_plan_round_robin_when_pool_smaller() -> None:
    bundle = ReplyBundle(
        answer_list=["同一句"],
        answer_keywords="tiny",
        message_pool=["仅甲", "仅乙"],
    )
    peers = (1, 2, 3, 4)
    chosen = [Responder.pick_fanout_plan(bundle, bid, peer_bot_ids=peers)[0][0] for bid in peers]
    assert chosen[0] != chosen[1]
    assert chosen[2] != chosen[3] or chosen[0] != chosen[2]
    assert set(chosen) <= {"仅甲", "仅乙"}


def test_pick_fanout_plan_stable_for_same_peers() -> None:
    bundle = ReplyBundle(
        answer_list=["同一句"],
        answer_keywords="stable",
        message_pool=["A", "B", "C", "D"],
    )
    peers = (9, 8, 7)
    first = [Responder.pick_fanout_plan(bundle, bid, peer_bot_ids=peers)[0][0] for bid in peers]
    second = [Responder.pick_fanout_plan(bundle, bid, peer_bot_ids=peers)[0][0] for bid in peers]
    assert first == second
