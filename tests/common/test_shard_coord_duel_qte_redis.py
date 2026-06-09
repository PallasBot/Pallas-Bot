from __future__ import annotations

import asyncio
import time

import pytest

from src.platform.shard.coord import duel_qte_redis as mod
from src.plugins.duel import duel_qte as qte_mod


def test_apply_greeting_envelope_updates_cluster_mirror() -> None:
    gid = "733291779"
    qte_mod._cluster_qte_users.clear()
    qte_mod._cluster_qte_deadline.clear()
    try:
        mod.apply_greeting_envelope({
            "gid": gid,
            "users": ["2964163468", "2136204582"],
            "deadline": time.time() + 20.0,
        })
        assert qte_mod.duel_qte_blocks_greeting_user(int(gid), "2964163468") is True
        mod.apply_greeting_envelope({"gid": gid, "users": None, "deadline": 0.0})
        assert qte_mod.duel_qte_blocks_greeting_user(int(gid), "2964163468") is False
    finally:
        qte_mod._cluster_qte_users.clear()
        qte_mod._cluster_qte_deadline.clear()


@pytest.mark.asyncio
async def test_duel_qte_session_listener_reads_messages_via_to_thread(monkeypatch) -> None:
    seen: list[str] = []

    class _PubSub:
        def subscribe(self, _channel: str) -> None:
            return None

        def get_message(self, *, timeout: float):
            seen.append(f"get:{timeout}")
            return {"type": "message", "data": '{"session_id":"sid-1"}'}

        def unsubscribe(self, _channel: str) -> None:
            return None

        def close(self) -> None:
            return None

    class _Client:
        def pubsub(self, *, ignore_subscribe_messages: bool):
            return _PubSub()

    async def fake_to_thread(fn, *args, **kwargs):
        seen.append("to_thread")
        return fn(*args, **kwargs)

    async def fake_wake(session_id: str, local_ids: frozenset[str]) -> None:
        seen.append(f"wake:{session_id}:{sorted(local_ids)}")
        raise asyncio.CancelledError

    monkeypatch.setattr("nonebot.get_bots", lambda: {"123": object()})
    monkeypatch.setattr(mod.asyncio, "to_thread", fake_to_thread)
    monkeypatch.setattr("src.platform.coord.redis_settings.coord_redis_enabled", lambda: True)
    monkeypatch.setattr("src.platform.coord.redis_claim.get_coord_redis_client", lambda: _Client())
    monkeypatch.setattr("src.platform.shard.coord.duel_qte.wake_duel_qte_session", fake_wake)

    with pytest.raises(asyncio.CancelledError):
        await mod.duel_qte_session_redis_listen_loop()

    assert seen[:2] == ["to_thread", "get:1.0"]
