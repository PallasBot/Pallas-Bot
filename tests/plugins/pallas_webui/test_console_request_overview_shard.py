from __future__ import annotations

import asyncio

import pytest

from src.plugins.pallas_webui import extended_api as mod


@pytest.mark.asyncio
async def test_friend_requests_overview_parallel_doubt(monkeypatch) -> None:
    monkeypatch.setattr(mod, "_read_pending_friend_requests_disk", dict)
    monkeypatch.setattr(
        mod,
        "get_bots",
        dict,
    )
    monkeypatch.setattr(mod, "_shard_hub_console", lambda: True)
    monkeypatch.setattr(
        "src.platform.shard.presence.read_presence_bots",
        lambda: {
            "10001": {"qq": 10001, "connection_key": "c1", "adapter": "OneBot V11"},
            "10002": {"qq": 10002, "connection_key": "c2", "adapter": "OneBot V11"},
        },
    )

    calls: list[int] = []

    async def fake_doubt(self_id: int) -> list[dict]:
        calls.append(self_id)
        await asyncio.sleep(0.01)
        return [{"user_id": self_id, "flag": "f", "nickname": ""}]

    monkeypatch.setattr(mod, "_doubt_friends_for_self_id_safe", fake_doubt)
    async def noop_enrich(*_a, **_k) -> None:
        return None

    monkeypatch.setattr(mod, "_enrich_friend_request_rows_nicknames_for_self_id", noop_enrich)

    out = await mod._friend_requests_overview(self_id=None, include_doubt=True)
    assert len(out["bots"]) == 2
    assert sorted(calls) == [10001, 10002]
    by_sid = {str(b["self_id"]): b for b in out["bots"]}
    assert len(by_sid["10001"]["doubt_friend_requests"]) == 1
    assert len(by_sid["10002"]["doubt_friend_requests"]) == 1


@pytest.mark.asyncio
async def test_friend_requests_overview_self_id_filter(monkeypatch) -> None:
    monkeypatch.setattr(
        mod,
        "_read_pending_friend_requests_disk",
        lambda: {"10001": {"9": "f1"}, "10002": {"8": "f2"}},
    )
    monkeypatch.setattr(mod, "get_bots", dict)
    monkeypatch.setattr(mod, "_shard_hub_console", lambda: False)

    out = await mod._friend_requests_overview(self_id="10001", include_doubt=False)
    assert [b["self_id"] for b in out["bots"]] == ["10001"]
    assert out["bots"][0]["pending_friend_requests"] == [{"user_id": 9, "flag": "f1"}]
