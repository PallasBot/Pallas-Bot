from __future__ import annotations

import pytest
from nonebot.adapters.onebot.v11 import GroupRecallNoticeEvent, NoticeEvent
from nonebot.exception import IgnoredException

from pallas.core.platform.ingress.notice_gate import ingress_notice_gate


class FakeBot:
    def __init__(self, self_id: int) -> None:
        self.self_id = str(self_id)


@pytest.mark.asyncio
async def test_ingress_notice_discards_emoji_like(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("pallas.core.platform.ingress.notice_gate.ingress_gate_runtime_active", lambda: True)
    event = NoticeEvent.model_construct(
        time=100,
        self_id=111,
        post_type="notice",
        notice_type="group_msg_emoji_like",
        group_id=12345,
        user_id=999,
        message_id=1,
    )
    with pytest.raises(IgnoredException, match="ingress notice discard"):
        await ingress_notice_gate(FakeBot(111), event)


@pytest.mark.asyncio
async def test_ingress_notice_discards_poke_not_for_self(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("pallas.core.platform.ingress.notice_gate.ingress_gate_runtime_active", lambda: True)
    event = NoticeEvent.model_construct(
        time=100,
        self_id=111,
        post_type="notice",
        notice_type="notify",
        sub_type="poke",
        group_id=12345,
        user_id=999,
        target_id=222,
    )
    with pytest.raises(IgnoredException, match="poke not for this bot"):
        await ingress_notice_gate(FakeBot(111), event)


@pytest.mark.asyncio
async def test_ingress_notice_recall_once_claim(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("pallas.core.platform.ingress.notice_gate.ingress_gate_runtime_active", lambda: True)
    event = GroupRecallNoticeEvent.model_construct(
        time=100,
        self_id=111,
        post_type="notice",
        notice_type="group_recall",
        group_id=12345,
        user_id=999,
        operator_id=888,
        message_id=42,
    )
    await ingress_notice_gate(FakeBot(111), event)
    with pytest.raises(IgnoredException, match="ingress notice once claim lost"):
        await ingress_notice_gate(FakeBot(222), event)
