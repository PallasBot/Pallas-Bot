"""酒后附带 TTS 阈值与开关。"""

from __future__ import annotations

import pytest

from pallas.product.llm.config import LlmConfig
from pallas.product.llm.drunk_tts import should_attach_drunk_tts


@pytest.mark.asyncio
async def test_should_attach_requires_enable(monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = LlmConfig(chat_tts_enable=False, drunk_tts_min_drunkenness=1, drunk_tts_min_chars=1)

    async def fake_drunk(*_a, **_k):
        return 10

    monkeypatch.setattr("pallas.product.llm.drunk_tts.BotConfig.drunkenness", fake_drunk)
    monkeypatch.setattr("pallas.product.llm.drunk_tts._tts_plugin_enabled", lambda: True)
    assert not await should_attach_drunk_tts(bot_id=1, group_id=2, reply_text="一二三四五六", cfg=cfg)


@pytest.mark.asyncio
async def test_should_attach_min_drunkenness_and_chars(monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = LlmConfig(chat_tts_enable=True, drunk_tts_min_drunkenness=1, drunk_tts_min_chars=6)
    level = {"v": 0}

    async def fake_drunk(*_a, **_k):
        return level["v"]

    monkeypatch.setattr("pallas.product.llm.drunk_tts.BotConfig.drunkenness", fake_drunk)
    monkeypatch.setattr("pallas.product.llm.drunk_tts._tts_plugin_enabled", lambda: True)

    level["v"] = 0
    assert not await should_attach_drunk_tts(bot_id=1, group_id=2, reply_text="一二三四五六", cfg=cfg)

    level["v"] = 1
    assert not await should_attach_drunk_tts(bot_id=1, group_id=2, reply_text="短", cfg=cfg)
    assert await should_attach_drunk_tts(bot_id=1, group_id=2, reply_text="一二三四五六", cfg=cfg)
