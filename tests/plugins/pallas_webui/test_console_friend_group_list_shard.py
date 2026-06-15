from __future__ import annotations

import pytest
from fastapi import HTTPException

from src.plugins.pallas_webui import extended_api as mod


def empty_bots():
    return {}


def test_console_bot_online_in_cluster(monkeypatch) -> None:
    monkeypatch.setattr(mod, "_shard_hub_console", lambda: True)
    monkeypatch.setattr(
        "src.platform.shard.presence.get_cluster_online_bot_ids",
        lambda: frozenset({10001}),
    )
    assert mod._console_bot_online_in_cluster("10001") is True
    assert mod._console_bot_online_in_cluster("99999") is False


def test_console_bot_connection_meta_from_presence(monkeypatch) -> None:
    monkeypatch.setattr(mod, "get_bots", empty_bots)
    monkeypatch.setattr(mod, "_console_bot_online_in_cluster", lambda _sid: True)
    monkeypatch.setattr(
        "src.platform.shard.presence.read_presence_bots",
        lambda: {
            "10001": {
                "qq": 10001,
                "connection_key": "conn-10001",
                "adapter": "OneBot V11",
            },
        },
    )
    conn, adapter = mod._console_bot_connection_meta(10001)
    assert conn == "conn-10001"
    assert adapter == "OneBot V11"


def test_console_bot_connection_meta_not_connected(monkeypatch) -> None:
    monkeypatch.setattr(mod, "get_bots", empty_bots)
    monkeypatch.setattr(mod, "_console_bot_online_in_cluster", lambda _sid: False)
    with pytest.raises(HTTPException) as exc:
        mod._console_bot_connection_meta(10001)
    assert exc.value.status_code == 404


def test_parse_friend_list_raw_truncates() -> None:
    raw = [{"user_id": i, "nickname": str(i)} for i in range(1, 5)]
    friends, err, truncated = mod._parse_friend_list_raw(raw, limit=2)
    assert err is None
    assert truncated is True
    assert len(friends) == 2
