from __future__ import annotations

import random

import pytest

from pallas.product.llm.low_engagement import (
    _GENTLE_POOL,
    _is_gentle_short_saying,
    clear_low_engagement_last_used,
    dispatch_low_engagement,
    low_engagement_emit_probability,
    pick_low_engagement_saying,
    should_emit_low_engagement,
)


@pytest.mark.parametrize(
    ("saying", "expected"),
    [
        ("哈哈", True),
        ("那没事了", True),
        ("嗯嗯", True),
        ("😄😄😄", True),
        ("这有意思", True),
        ("你俩这是要组个妈妈联盟啊", True),  # 11 字，仍短
        ("这是一句超过十二个字符的超长表达", False),  # 超过 12 字
        ("你在吗", False),  # 问句尾
        ("？", False),  # 问号
        ("好吗", False),  # 语气词尾
        ("[CQ:face,id=0]", False),  # CQ 码
        ("", False),  # 空
    ],
)
def test_is_gentle_short_saying(saying: str, expected: bool) -> None:
    assert _is_gentle_short_saying(saying) is expected


def test_is_gentle_short_saying_rejects_question_tail() -> None:
    assert not _is_gentle_short_saying("好吗")
    assert not _is_gentle_short_saying("怎么办呀")
    assert not _is_gentle_short_saying("？")


def test_low_engagement_emit_probability_tiers() -> None:
    assert low_engagement_emit_probability(0) == 0.35
    assert low_engagement_emit_probability(1) == 0.20
    assert low_engagement_emit_probability(2) == 0.20
    assert low_engagement_emit_probability(3) == 0.10
    assert low_engagement_emit_probability(4) == 0.10
    assert low_engagement_emit_probability(5) == 0.05
    assert low_engagement_emit_probability(99) == 0.05


def test_low_engagement_emit_probability_clamps_negative() -> None:
    assert low_engagement_emit_probability(-3) == 0.35


def test_should_emit_low_engagement_respects_probability() -> None:
    class StubRng:
        def __init__(self, value: float) -> None:
            self.value = value

        def random(self) -> float:
            return self.value

    assert should_emit_low_engagement(0, rng=StubRng(0.0)) is True
    assert should_emit_low_engagement(0, rng=StubRng(0.35)) is False  # < 严格
    assert should_emit_low_engagement(0, rng=StubRng(0.99)) is False
    # 低投入档位更低的概率：3-4 条 Bot 回复后 0.1
    assert should_emit_low_engagement(3, rng=StubRng(0.05)) is True
    assert should_emit_low_engagement(3, rng=StubRng(0.2)) is False


def test_pick_low_engagement_saying_returns_from_static_pool_when_no_group_data() -> None:
    saying = pick_low_engagement_saying(group_id=999999, rng=random.Random(1))
    assert isinstance(saying, str)
    assert saying in (_GENTLE_POOL + ["😄😄😄", "哈哈哈哈", "（（", "（", "www"])


def test_pick_low_engagement_saying_avoids_immediate_repeat_for_same_group() -> None:
    clear_low_engagement_last_used()
    group_id = 999998
    first = pick_low_engagement_saying(group_id, rng=random.Random(1))
    second = pick_low_engagement_saying(group_id, rng=random.Random(1))
    assert first != second
    clear_low_engagement_last_used()


def test_clear_last_used_allows_repeat() -> None:
    clear_low_engagement_last_used()
    group_id = 999997
    first = pick_low_engagement_saying(group_id, rng=random.Random(1))
    clear_low_engagement_last_used()
    second = pick_low_engagement_saying(group_id, rng=random.Random(1))
    assert first == second
    clear_low_engagement_last_used()


@pytest.mark.asyncio
async def test_dispatch_low_engagement_sends_and_records(monkeypatch) -> None:
    sent: list[str] = []

    async def fake_send(text: str) -> None:
        sent.append(text)

    recorded: list[str] = []

    def fake_record(*args: object, **kwargs: object) -> None:
        recorded.append(str(kwargs.get("metric") or args[1] if len(args) > 1 else ""))

    traced: list[dict[str, object]] = []

    def fake_trace(payload: dict[str, object]) -> None:
        traced.append(payload)

    monkeypatch.setattr("pallas.product.llm.task_metrics.record_bot_llm_task", fake_record)
    monkeypatch.setattr("packages.repeater.opportunity_trace.append_conversation_decision_trace", fake_trace)

    class AlwaysRollRng(random.Random):
        def random(self) -> float:
            return 0.0

    # 大概率命中（count=0, rng 0.0）
    clear_low_engagement_last_used()
    emitted = await dispatch_low_engagement(
        bot_id=1,
        group_id=123,
        user_id=456,
        recent_bot_reply_count=0,
        send_message=fake_send,
        rng=AlwaysRollRng(1),
    )

    assert emitted is True
    assert len(sent) == 1
    assert recorded == ["low_engagement_emit"]
    assert traced
    assert traced[0]["kind"] == "low_engagement_emit"
    assert traced[0]["saying"] == sent[0]


@pytest.mark.asyncio
async def test_dispatch_low_engagement_can_stay_silent() -> None:
    sent: list[str] = []

    async def fake_send(text: str) -> None:
        sent.append(text)

    clear_low_engagement_last_used()
    emitted = await dispatch_low_engagement(
        bot_id=1,
        group_id=123,
        user_id=456,
        recent_bot_reply_count=99,
        send_message=fake_send,
        rng=type("Rng", (), {"random": lambda self: 0.99})(),
    )

    assert emitted is False
    assert sent == []
