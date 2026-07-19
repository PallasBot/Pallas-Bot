from __future__ import annotations

import json
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from packages.pb_core import restart_notify as mod


@pytest.fixture
def notify_dir(tmp_path, monkeypatch):
    monkeypatch.setattr("packages.pb_core.restart_notify.plugin_data_dir", lambda _name, create=True: tmp_path)
    return tmp_path


def test_record_and_load_restart_notify(notify_dir):
    mod.record_restart_notify(user_id=111, bot_id=222, mode="unified")
    pending = mod.load_restart_notify_pending()
    assert pending is not None
    assert pending.user_id == 111
    assert pending.bot_id == 222
    assert pending.mode == "unified"


def test_load_restart_notify_expired(notify_dir):
    path = notify_dir / "restart_notify_pending.json"
    path.write_text(
        json.dumps({
            "user_id": 111,
            "bot_id": 222,
            "mode": "unified",
            "requested_at": time.time() - mod._PENDING_TTL_SEC - 1,
        }),
        encoding="utf-8",
    )
    assert mod.load_restart_notify_pending() is None
    assert not path.is_file()


def test_format_restart_online_message():
    assert mod.format_restart_online_message(bot_id=3888888888, mode="shard") == (
        "牛牛 3888888888 已重新上线（shard），重启完成。"
    )


@pytest.mark.asyncio
async def test_maybe_notify_restart_online_sends_and_clears(notify_dir, monkeypatch):
    mod.record_restart_notify(user_id=111, bot_id=222, mode="unified")
    bot = SimpleNamespace(self_id="222", type="OneBot V11")
    bot.send_private_msg = AsyncMock()
    await mod.maybe_notify_restart_online(bot)
    bot.send_private_msg.assert_awaited_once_with(
        user_id=111,
        message="牛牛 222 已重新上线（unified），重启完成。",
    )
    assert mod.load_restart_notify_pending() is None


@pytest.mark.asyncio
async def test_maybe_notify_restart_online_waits_for_matching_bot(notify_dir):
    mod.record_restart_notify(user_id=111, bot_id=222, mode="unified")
    bot = SimpleNamespace(self_id="333", type="OneBot V11")
    bot.send_private_msg = AsyncMock()
    await mod.maybe_notify_restart_online(bot)
    bot.send_private_msg.assert_not_awaited()
    assert mod.load_restart_notify_pending() is not None
