from __future__ import annotations

import json
import time

from src.common.shard.coord.ai_task_registry import (
    register_ai_task,
    remove_ai_task,
    resolve_worker_port_for_task,
)


def test_register_and_resolve_worker_port(tmp_path, monkeypatch):
    shard_root = tmp_path / "pallas_shard"
    shard_root.mkdir(parents=True)
    (shard_root / "registry.json").write_text(
        json.dumps(
            {
                "bots_per_shard": 5,
                "hub_port": 8088,
                "worker_base_port": 7970,
                "ws_path": "/onebot/v11/ws",
                "ws_host": "127.0.0.1",
                "assignments": {"10001": 1},
                "shards": [
                    {"id": 0, "port": 7970, "bot_ids": []},
                    {"id": 1, "port": 7971, "bot_ids": ["10001"]},
                ],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("PALLAS_SHARD_ENABLED", "true")
    monkeypatch.setenv("PALLAS_BOT_ROLE", "worker")
    monkeypatch.setattr(
        "src.common.shard.registry.store._registry_path",
        lambda: shard_root / "registry.json",
    )
    monkeypatch.setattr(
        "src.common.shard.coord.ai_task_registry.plugin_data_dir",
        lambda *_a, **_k: shard_root,
    )

    task_id = "01ARZ3NDEKTSV4RRFFQ69G5FAV"
    register_ai_task(
        task_id,
        {"bot_id": "10001", "group_id": 12345, "start_time": time.time()},
    )
    assert resolve_worker_port_for_task(task_id) == 7971

    remove_ai_task(task_id)
    assert resolve_worker_port_for_task(task_id) is None
