from __future__ import annotations

import asyncio
import time

from src.common.shard.coord import bot_action as mod


def test_bot_action_request_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setattr(mod, "_coord_dir", lambda: tmp_path)

    request_id = mod._publish_request(
        action="set_group_card",
        bot_qq=300,
        payload={"group_id": 1, "user_id": 2, "card": "test"},
        timeout_sec=5.0,
    )
    path = mod._request_path(request_id)
    mod._finish_request(path, ok=True, result=None)

    async def run() -> None:
        ok, result = await mod._wait_request(request_id, deadline=time.time() + 2.0)
        assert ok is True
        assert result is None

    asyncio.run(run())
