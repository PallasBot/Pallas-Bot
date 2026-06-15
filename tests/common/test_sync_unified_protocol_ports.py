from __future__ import annotations

import json
from typing import TYPE_CHECKING

from src.platform.shard.registry.sync_unified_protocol_ports import (
    resolve_unified_listen_port,
    sync_accounts_ws_urls_unified,
)

if TYPE_CHECKING:
    from pathlib import Path


def test_resolve_unified_listen_port_from_env(tmp_path: Path) -> None:
    env_path = tmp_path / ".env"
    env_path.write_text("PORT=9001\n", encoding="utf-8")
    assert resolve_unified_listen_port(env_path=env_path) == 9001


def test_sync_unified_protocol_ports_no_change_when_aligned(tmp_path: Path) -> None:
    proto = tmp_path / "pallas_protocol"
    proto.mkdir(parents=True)
    accounts_path = proto / "accounts.json"
    env_path = tmp_path / ".env"
    env_path.write_text("PORT=8088\nPALLAS_SHARD_WS_HOST=127.0.0.1\n", encoding="utf-8")
    accounts_path.write_text(
        json.dumps({
            "a1": {
                "qq": "100",
                "enabled": True,
                "ws_url": "ws://127.0.0.1:8088/onebot/v11/ws",
            }
        }),
        encoding="utf-8",
    )

    result = sync_accounts_ws_urls_unified(accounts_path, env_path=env_path, dry_run=True)
    assert result.changed_count == 0


def test_sync_unified_protocol_ports_updates_worker_url(tmp_path: Path) -> None:
    proto = tmp_path / "pallas_protocol"
    proto.mkdir(parents=True)
    accounts_path = proto / "accounts.json"
    env_path = tmp_path / ".env"
    env_path.write_text("PORT=8088\nPALLAS_SHARD_WS_HOST=127.0.0.1\n", encoding="utf-8")
    accounts_path.write_text(
        json.dumps({
            "a1": {
                "qq": "100",
                "enabled": True,
                "ws_url": "ws://127.0.0.1:8090/onebot/v11/ws",
            }
        }),
        encoding="utf-8",
    )

    result = sync_accounts_ws_urls_unified(accounts_path, env_path=env_path, dry_run=True)
    assert result.changed_count == 1
    assert result.details[0]["new"] == "ws://127.0.0.1:8088/onebot/v11/ws"
