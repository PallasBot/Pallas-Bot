from __future__ import annotations

import json
import time

from pallas.core.platform.shard.coord.ai_task_registry import (
    get_ai_task_record,
    register_ai_task,
    remove_ai_task,
    resolve_worker_port_for_task,
)
from pallas.core.platform.shard.registry.config import get_shard_registry_settings


def test_register_and_resolve_worker_port(tmp_path, monkeypatch):
    shard_root = tmp_path / "pallas_shard"
    shard_root.mkdir(parents=True)
    (shard_root / "registry.json").write_text(
        json.dumps({
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
        }),
        encoding="utf-8",
    )
    monkeypatch.setenv("PALLAS_SHARD_ENABLED", "true")
    monkeypatch.setenv("PALLAS_BOT_ROLE", "worker")
    monkeypatch.setenv("PALLAS_SHARD_ID", "2")
    get_shard_registry_settings.cache_clear()
    monkeypatch.setattr(
        "pallas.core.platform.shard.registry.store._registry_path",
        lambda: shard_root / "registry.json",
    )
    task_id = "01ARZ3NDEKTSV4RRFFQ69G5FAV"
    register_ai_task(
        task_id,
        {"bot_id": "10001", "group_id": 12345, "start_time": time.time()},
    )
    assert resolve_worker_port_for_task(task_id) == 7972
    rec = get_ai_task_record(task_id)
    assert rec is not None
    assert rec["shard_id"] == 2
    assert rec["worker_port"] == 7972

    remove_ai_task(task_id)
    assert resolve_worker_port_for_task(task_id) is None
