from __future__ import annotations

import json
import time
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from pallas.core.platform.coord import redis_presence as rp
from pallas.core.platform.shard import presence as mod


@pytest.fixture(autouse=True)
def force_file_presence(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(rp, "presence_uses_redis_only", lambda: False)
    monkeypatch.setattr(rp, "get_presence_redis_client", lambda: None)


def test_presence_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setattr(mod, "plugin_data_dir", lambda name, create=True: tmp_path / name)
    monkeypatch.setattr(mod, "is_sharding_active", lambda: True)

    mod.note_worker_bot_connected_sync(qq=111, connection_key="111", adapter="OneBot V11", shard_id=0)
    mod.note_worker_bot_connected_sync(qq=222, connection_key="222", adapter="OneBot V11", shard_id=1)

    online = mod.get_cluster_online_bot_ids()
    assert 111 in online
    assert 222 in online

    rows = mod.list_connected_bots_for_webui()
    assert len(rows) == 2
    assert {r["self_id"] for r in rows} == {"111", "222"}

    mod.note_worker_bot_disconnected_sync(qq=111)
    assert 111 not in mod.get_cluster_online_bot_ids()


def test_presence_stale_pruned(tmp_path, monkeypatch):
    monkeypatch.setattr(mod, "plugin_data_dir", lambda name, create=True: tmp_path / name)
    monkeypatch.setattr(mod, "is_sharding_active", lambda: True)

    mod.note_worker_bot_connected_sync(qq=333, connection_key="333", adapter="OneBot V11", shard_id=0)
    path = mod._presence_path()
    data = json.loads(path.read_text(encoding="utf-8"))
    data["bots"]["333"]["last_seen_at"] = time.time() - 9999
    path.write_text(json.dumps(data), encoding="utf-8")

    assert 333 not in mod.get_cluster_online_bot_ids()


def test_presence_redis_roundtrip(monkeypatch: pytest.MonkeyPatch) -> None:
    store: dict[str, str] = {}
    meta: dict[str, str] = {}

    client = MagicMock()

    def hset(name, key, value):
        store[str(key)] = value

    def hget(name, key):
        return store.get(str(key))

    def hgetall(name):
        return dict(store)

    def hdel(name, key):
        store.pop(str(key), None)

    def hlen(name):
        return len(store)

    def get(key):
        return meta.get(str(key))

    def set_(key, value):
        meta[str(key)] = str(value)

    client.hset.side_effect = hset
    client.hget.side_effect = hget
    client.hgetall.side_effect = hgetall
    client.hdel.side_effect = hdel
    client.hlen.side_effect = hlen
    client.get.side_effect = get
    client.set.side_effect = set_
    client.pipeline.return_value = client
    client.execute.return_value = None

    monkeypatch.setattr(rp, "get_presence_redis_client", lambda: client)
    monkeypatch.setattr(rp, "presence_uses_redis_only", lambda: True)
    monkeypatch.setattr(mod, "is_sharding_active", lambda: True)
    monkeypatch.setattr(mod, "_read_file_bots", dict)

    mod.note_worker_bot_connected_sync(qq=111, connection_key="111", adapter="OneBot V11", shard_id=0)
    assert mod.get_cluster_online_bot_ids() == frozenset({111})

    mod.note_worker_bot_disconnected_sync(qq=111)
    assert mod.get_cluster_online_bot_ids() == frozenset()


def test_presence_imports_file_when_redis_empty(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(mod, "plugin_data_dir", lambda name, create=True: tmp_path / name)
    monkeypatch.setattr(mod, "is_sharding_active", lambda: True)

    mod.note_worker_bot_connected_sync(qq=444, connection_key="444", adapter="OneBot V11", shard_id=2)
    file_bots = mod._read_file_bots()
    assert "444" in file_bots

    store: dict[str, str] = {}

    client = MagicMock()
    client.hgetall.side_effect = lambda _name: dict(store)
    client.hlen.side_effect = lambda _name: len(store)
    client.get.return_value = None

    def hset(name, key, value):
        store[str(key)] = value

    client.hset.side_effect = hset
    client.pipeline.return_value = client
    client.execute.return_value = None
    client.set.return_value = True

    monkeypatch.setattr(rp, "get_presence_redis_client", lambda: client)
    monkeypatch.setattr(rp, "presence_uses_redis_only", lambda: True)

    loaded = mod._load_presence_bots()
    assert "444" in loaded
    assert loaded["444"]["shard_id"] == 2


def test_reconcile_redis_upserts_missing_local_bot(monkeypatch: pytest.MonkeyPatch) -> None:
    store: dict[str, str] = {}

    client = MagicMock()

    def hset(name, key, value):
        store[str(key)] = value

    def hgetall(name):
        return dict(store)

    client.hset.side_effect = hset
    client.hgetall.side_effect = hgetall
    client.pipeline.return_value = client
    client.execute.return_value = None
    client.set.return_value = True

    monkeypatch.setattr(rp, "get_presence_redis_client", lambda: client)
    monkeypatch.setattr(rp, "presence_uses_redis_only", lambda: True)
    monkeypatch.setattr(mod, "is_sharding_active", lambda: True)
    monkeypatch.setattr(mod, "_read_file_bots", dict)

    rp.note_worker_bot_connected_redis_sync(
        qq=222,
        connection_key="222",
        adapter="OneBot V11",
        shard_id=1,
        nickname="other-shard",
    )
    assert "111" not in store

    mod.reconcile_local_worker_presence_sync(shard_id=0, local_qq_ids={111, 333})

    assert "111" in store
    rec = json.loads(store["111"])
    assert rec["shard_id"] == 0
    assert rec["qq"] == 111
    assert "222" in store


def test_reconcile_file_upserts_missing_local_bot(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(mod, "plugin_data_dir", lambda name, create=True: tmp_path / name)
    monkeypatch.setattr(mod, "is_sharding_active", lambda: True)

    mod.note_worker_bot_connected_sync(qq=222, connection_key="222", adapter="OneBot V11", shard_id=1)
    mod.reconcile_local_worker_presence_sync(shard_id=0, local_qq_ids={111})

    bots = mod._read_file_bots()
    assert "111" in bots
    assert bots["111"]["shard_id"] == 0
    assert "222" in bots
    assert 111 in mod.get_cluster_online_bot_ids()


def test_protocol_offline_clears_presence_and_blocks_reconcile(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(mod, "plugin_data_dir", lambda name, create=True: tmp_path / name)
    monkeypatch.setattr(mod, "is_sharding_active", lambda: True)
    mod.clear_protocol_bot_offline_sync(qq=111)

    mod.note_worker_bot_connected_sync(qq=111, connection_key="111", adapter="OneBot V11", shard_id=0)
    assert 111 in mod.get_cluster_online_bot_ids()

    mod.mark_protocol_bot_offline_sync(qq=111)
    assert 111 not in mod.get_cluster_online_bot_ids()

    filtered = mod.filter_local_qq_ids_for_presence({111})
    assert filtered == set()
    mod.reconcile_local_worker_presence_sync(shard_id=0, local_qq_ids=filtered)
    assert 111 not in mod.get_cluster_online_bot_ids()

    mod.clear_protocol_bot_offline_sync(qq=111)
    mod.reconcile_local_worker_presence_sync(shard_id=0, local_qq_ids={111})
    assert 111 in mod.get_cluster_online_bot_ids()


def test_touch_missing_presence_does_not_write_file(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(mod, "plugin_data_dir", lambda name, create=True: tmp_path / name)
    monkeypatch.setattr(mod, "is_sharding_active", lambda: True)

    writes: list[dict[str, object]] = []
    real_write = mod._write_atomic

    def wrapped(data):
        writes.append(dict(data))
        real_write(data)

    monkeypatch.setattr(mod, "_write_atomic", wrapped)

    mod.touch_worker_bot_presence_sync(qq=111)

    assert writes == []
    assert not mod._presence_path().exists()


def test_disconnect_missing_presence_does_not_write_file(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(mod, "plugin_data_dir", lambda name, create=True: tmp_path / name)
    monkeypatch.setattr(mod, "is_sharding_active", lambda: True)

    writes: list[dict[str, object]] = []
    real_write = mod._write_atomic

    def wrapped(data):
        writes.append(dict(data))
        real_write(data)

    monkeypatch.setattr(mod, "_write_atomic", wrapped)

    mod.note_worker_bot_disconnected_sync(qq=111)

    assert writes == []
    assert not mod._presence_path().exists()


@pytest.mark.asyncio
async def test_note_worker_bot_connected_does_not_call_login_info(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(mod, "is_sharding_active", lambda: True)
    monkeypatch.setattr(mod, "get_shard_registry_settings", lambda: SimpleNamespace(shard_id=7))

    captured: dict[str, object] = {}

    async def fake_to_thread(fn, /, *args, **kwargs):
        captured["fn"] = fn
        captured["kwargs"] = kwargs
        return None

    monkeypatch.setattr(mod.asyncio, "to_thread", fake_to_thread)

    class _Adapter:
        @staticmethod
        def get_name() -> str:
            return "OneBot V11"

    class _Bot:
        self_id = "123456"
        adapter = _Adapter()

        async def call_api(self, *_args, **_kwargs):
            raise AssertionError("get_login_info should not be called during bot_connect")

    await mod.note_worker_bot_connected(_Bot())

    assert captured["fn"] is mod.note_worker_bot_connected_sync
    assert captured["kwargs"] == {
        "qq": 123456,
        "connection_key": "123456",
        "adapter": "OneBot V11",
        "shard_id": 7,
        "nickname": "",
    }
