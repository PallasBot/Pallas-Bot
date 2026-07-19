from __future__ import annotations

from packages.repeater.responder import ReplyBundle, Responder


def test_pick_fanout_plan_differs_by_bot_id() -> None:
    bundle = ReplyBundle(
        answer_list=["同一句"],
        answer_keywords="kw",
        message_pool=["句子甲", "句子乙", "句子丙", "句子丁"],
    )
    plans = {Responder.pick_fanout_plan(bundle, bot_id)[0][0] for bot_id in (10001, 10002, 10003, 10004)}
    assert len(plans) >= 2
