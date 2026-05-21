from __future__ import annotations

import json
from unittest.mock import patch

from src.common.shard.registry.startup_ports import evaluate_shard_startup_ports


def test_evaluate_skips_when_registry_and_protocol_aligned(tmp_path, monkeypatch):
    proto = tmp_path / "pallas_protocol"
    proto.mkdir(parents=True)
    accounts_path = proto / "accounts.json"
    env_path = tmp_path / ".env"
    env_path.write_text(
        "PALLAS_SHARD_ENABLED=true\nPALLAS_SHARD_WORKER_BASE_PORT=8090\n"
        "PALLAS_SHARD_WS_HOST=127.0.0.1\n",
        encoding="utf-8",
    )
    reg_dir = tmp_path / "pallas_shard"
    reg_dir.mkdir(parents=True)
    (reg_dir / "registry.json").write_text(
        json.dumps(
            {
                "bots_per_shard": 5,
                "hub_port": 8088,
                "worker_base_port": 8090,
                "ws_path": "/onebot/v11/ws",
                "ws_host": "127.0.0.1",
                "assignments": {"100": 0},
                "shards": [{"id": 0, "port": 8090, "bot_ids": ["100"]}],
            }
        ),
        encoding="utf-8",
    )
    accounts_path.write_text(
        json.dumps(
            {
                "a1": {
                    "qq": "100",
                    "enabled": True,
                    "ws_url": "ws://127.0.0.1:8090/onebot/v11/ws",
                }
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("PALLAS_SHARD_ENABLED", "true")
    monkeypatch.setattr(
        "src.common.shard.registry.store._registry_path",
        lambda: reg_dir / "registry.json",
    )
    with patch("src.common.shard.registry.port_alloc.is_tcp_port_in_use", return_value=False):
        ev = evaluate_shard_startup_ports(
            1,
            8090,
            accounts_path=accounts_path,
            env_path=env_path,
            skip_occupied=True,
        )
    assert ev.skip_registry_alloc is True
    assert ev.skip_protocol_sync is True
    assert ev.worker_ports == [8090]
