from __future__ import annotations

import json
from unittest.mock import MagicMock

from pallas.core.platform.federate import peer_bots as mod


def test_publish_local_federate_peer_bot_ids_sync_writes_current_catalog(monkeypatch):
    client = MagicMock()
    monkeypatch.setattr(mod, "get_federate_redis_client", lambda: client)
    monkeypatch.setattr(mod, "federate_redis_prefix", lambda _cfg=None: "pallas:fed:pool-1")
    monkeypatch.setattr(mod, "load_or_create_deployment_id", lambda: "dep-local")
    monkeypatch.setattr(mod, "get_catalog_bot_ids", lambda: frozenset({111, 222}))

    assert mod.publish_local_federate_peer_bot_ids_sync() is True
    key, payload = client.set.call_args.args[:2]
    assert key == "pallas:fed:pool-1:peer_bots:dep-local"
    assert set(json.loads(payload)["bot_ids"]) == {111, 222}
    assert client.set.call_args.kwargs["ex"] > 0


def test_refresh_federate_peer_bot_ids_sync_reads_other_deployments(monkeypatch):
    client = MagicMock()
    client.scan_iter.return_value = iter([
        b"pallas:fed:pool-1:peer_bots:dep-local",
        b"pallas:fed:pool-1:peer_bots:dep-a",
        b"pallas:fed:pool-1:peer_bots:dep-b",
    ])
    client.get.side_effect = lambda key: {
        "pallas:fed:pool-1:peer_bots:dep-local": json.dumps({"bot_ids": [111]}),
        "pallas:fed:pool-1:peer_bots:dep-a": json.dumps({"bot_ids": [222, 333]}),
        "pallas:fed:pool-1:peer_bots:dep-b": json.dumps({"bot_ids": [333, 444]}),
    }[key.decode("utf-8") if isinstance(key, bytes) else key]
    monkeypatch.setattr(mod, "get_federate_redis_client", lambda: client)
    monkeypatch.setattr(mod, "federate_redis_prefix", lambda _cfg=None: "pallas:fed:pool-1")
    monkeypatch.setattr(mod, "load_or_create_deployment_id", lambda: "dep-local")

    assert mod.refresh_federate_peer_bot_ids_sync() == frozenset({222, 333, 444})
    assert mod.get_federate_peer_deployment_ids() == frozenset({"dep-a", "dep-b"})


def test_should_process_federate_group_on_current_deployment_uses_sorted_owner_ring(monkeypatch):
    mod.clear_federate_peer_bot_cache_for_tests()
    monkeypatch.setattr(mod, "load_or_create_deployment_id", lambda: "dep-b")
    monkeypatch.setattr(mod, "federate_ingress_active", lambda: True)
    mod._cache_deployment_ids = frozenset({"dep-a", "dep-c"})

    assert mod.federate_group_owner_deployment(123) == "dep-a"
    assert mod.should_process_federate_group_on_current_deployment(124) is True
    assert mod.should_process_federate_group_on_current_deployment(125) is False
