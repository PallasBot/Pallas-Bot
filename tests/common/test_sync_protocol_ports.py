from __future__ import annotations

import json

from pallas.core.platform.shard.registry.sync_protocol_ports import (
    onebot_instance_ws_drifted,
    sync_accounts_ws_urls,
    sync_onebot_instances_from_accounts,
)


def test_sync_protocol_ports_no_change_when_already_aligned(tmp_path, monkeypatch):
    proto = tmp_path / "pallas_protocol"
    proto.mkdir(parents=True)
    accounts_path = proto / "accounts.json"
    env_path = tmp_path / ".env"
    env_path.write_text(
        "PALLAS_SHARD_ENABLED=true\nPALLAS_SHARD_WORKER_BASE_PORT=8090\nPALLAS_SHARD_WS_HOST=127.0.0.1\n",
        encoding="utf-8",
    )
    reg_dir = tmp_path / "pallas_shard"
    reg_dir.mkdir(parents=True)
    (reg_dir / "registry.json").write_text(
        json.dumps({
            "bots_per_shard": 5,
            "hub_port": 8088,
            "worker_base_port": 8090,
            "ws_path": "/onebot/v11/ws",
            "ws_host": "127.0.0.1",
            "assignments": {"100": 0},
            "shards": [{"id": 0, "port": 8090, "bot_ids": ["100"]}],
        }),
        encoding="utf-8",
    )
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
    monkeypatch.setenv("PALLAS_SHARD_ENABLED", "true")
    monkeypatch.setattr(
        "pallas.core.platform.shard.registry.store._registry_path",
        lambda: reg_dir / "registry.json",
    )

    result = sync_accounts_ws_urls(accounts_path, env_path=env_path, dry_run=True)
    assert result.changed_count == 0


def test_sync_protocol_ports_detects_port_drift(tmp_path, monkeypatch):
    proto = tmp_path / "pallas_protocol"
    proto.mkdir(parents=True)
    accounts_path = proto / "accounts.json"
    env_path = tmp_path / ".env"
    env_path.write_text(
        "PALLAS_SHARD_ENABLED=true\nPALLAS_SHARD_WORKER_BASE_PORT=8090\nPALLAS_SHARD_WS_HOST=127.0.0.1\n",
        encoding="utf-8",
    )
    reg_dir = tmp_path / "pallas_shard"
    reg_dir.mkdir(parents=True)
    (reg_dir / "registry.json").write_text(
        json.dumps({
            "bots_per_shard": 5,
            "hub_port": 8088,
            "worker_base_port": 8090,
            "ws_path": "/onebot/v11/ws",
            "ws_host": "127.0.0.1",
            "assignments": {"200": 1},
            "shards": [
                {"id": 0, "port": 8090, "bot_ids": []},
                {"id": 1, "port": 8091, "bot_ids": ["200"]},
            ],
        }),
        encoding="utf-8",
    )
    accounts_path.write_text(
        json.dumps({
            "a2": {
                "qq": "200",
                "enabled": True,
                "ws_url": "ws://127.0.0.1:8090/onebot/v11/ws",
            }
        }),
        encoding="utf-8",
    )
    monkeypatch.setenv("PALLAS_SHARD_ENABLED", "true")
    monkeypatch.setattr(
        "pallas.core.platform.shard.registry.store._registry_path",
        lambda: reg_dir / "registry.json",
    )

    result = sync_accounts_ws_urls(accounts_path, env_path=env_path, dry_run=True)
    assert result.changed_count == 1
    assert result.details[0].get("port") == 8091


def test_sync_onebot_instances_detects_drift(tmp_path):
    instance_dir = tmp_path / "instances" / "100"
    config_dir = instance_dir / "config"
    config_dir.mkdir(parents=True)
    (config_dir / "onebot11_100.json").write_text(
        json.dumps({
            "network": {
                "websocketClients": [{"enable": True, "url": "ws://172.17.0.1:8090/onebot/v11/ws"}],
            }
        }),
        encoding="utf-8",
    )
    accounts = {
        "a1": {
            "qq": "100",
            "enabled": True,
            "ws_url": "ws://172.17.0.1:8091/onebot/v11/ws",
            "account_data_dir": str(instance_dir),
        }
    }
    assert onebot_instance_ws_drifted(accounts["a1"]) is True

    synced, drift = sync_onebot_instances_from_accounts(accounts, dry_run=False)
    assert synced == 1
    assert drift == 1
    data = json.loads((config_dir / "onebot11_100.json").read_text(encoding="utf-8"))
    assert data["network"]["websocketClients"][0]["url"] == "ws://172.17.0.1:8091/onebot/v11/ws"
