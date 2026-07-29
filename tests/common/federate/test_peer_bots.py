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
    monkeypatch.setattr(
        mod,
        "collect_local_federate_command_capabilities",
        lambda: frozenset({"牛牛塔罗牌", "牛牛帮助"}),
    )

    assert mod.publish_local_federate_peer_bot_ids_sync() is True
    key, payload = client.set.call_args.args[:2]
    assert key == "pallas:fed:pool-1:peer_bots:dep-local"
    data = json.loads(payload)
    assert set(data["bot_ids"]) == {111, 222}
    assert set(data["command_capabilities"]) == {"牛牛塔罗牌", "牛牛帮助"}
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
        "pallas:fed:pool-1:peer_bots:dep-a": json.dumps(
            {"bot_ids": [222, 333], "command_capabilities": ["牛牛帮助"]}
        ),
        "pallas:fed:pool-1:peer_bots:dep-b": json.dumps({"bot_ids": [333, 444]}),
    }[key.decode("utf-8") if isinstance(key, bytes) else key]
    monkeypatch.setattr(mod, "get_federate_redis_client", lambda: client)
    monkeypatch.setattr(mod, "federate_redis_prefix", lambda _cfg=None: "pallas:fed:pool-1")
    monkeypatch.setattr(mod, "load_or_create_deployment_id", lambda: "dep-local")

    assert mod.refresh_federate_peer_bot_ids_sync() == frozenset({222, 333, 444})
    assert mod.get_federate_peer_deployment_ids() == frozenset({"dep-a", "dep-b"})
    assert mod.get_federate_peer_command_capabilities("dep-a") == frozenset({"牛牛帮助"})
    assert mod.get_federate_peer_command_capabilities("dep-b") is None


def test_owner_ring_filters_to_deployments_that_advertise_command(monkeypatch):
    """有能力宣告时，只在「宣称能处理该命令」的部署里取模。"""
    mod.clear_federate_peer_bot_cache_for_tests()
    monkeypatch.setattr(mod, "load_or_create_deployment_id", lambda: "dep-local")
    monkeypatch.setattr(mod, "federate_ingress_active", lambda: True)
    monkeypatch.setattr(mod, "federate_owner_rotate_sec", lambda: 0)
    monkeypatch.setattr(mod, "federate_prefer_local_owner", lambda: False)
    monkeypatch.setattr(mod, "collect_local_federate_command_capabilities", lambda: frozenset({"牛牛塔罗牌"}))
    mod._cache_deployment_ids = frozenset({"dep-peer"})
    mod._cache_deployment_capabilities = {
        "dep-peer": frozenset({"牛牛帮助"}),  # 无塔罗
    }

    # 全员环里 dep-peer 可能当主人；按能力过滤后只剩本机
    assert mod.federate_group_owner_deployment(733291779, plain="牛牛塔罗牌") == "dep-local"
    assert mod.should_process_federate_group_on_current_deployment(733291779, plain="牛牛塔罗牌") is True


def test_owner_ring_keeps_legacy_peer_without_capabilities_field(monkeypatch):
    """未升级对端（无 capabilities 字段）仍视为全能，保持兼容。"""
    mod.clear_federate_peer_bot_cache_for_tests()
    monkeypatch.setattr(mod, "load_or_create_deployment_id", lambda: "dep-b")
    monkeypatch.setattr(mod, "federate_ingress_active", lambda: True)
    monkeypatch.setattr(mod, "federate_owner_rotate_sec", lambda: 0)
    monkeypatch.setattr(mod, "federate_prefer_local_owner", lambda: False)
    monkeypatch.setattr(mod, "collect_local_federate_command_capabilities", lambda: frozenset({"牛牛塔罗牌"}))
    mod._cache_deployment_ids = frozenset({"dep-a", "dep-c"})
    mod._cache_deployment_capabilities = {
        "dep-a": None,
        "dep-c": None,
    }

    assert mod.federate_group_owner_deployment(123, plain="牛牛塔罗牌") == "dep-a"
    assert mod.should_process_federate_group_on_current_deployment(124, plain="牛牛塔罗牌") is True


def test_should_process_federate_group_on_current_deployment_uses_sorted_owner_ring(monkeypatch):
    mod.clear_federate_peer_bot_cache_for_tests()
    monkeypatch.setattr(mod, "load_or_create_deployment_id", lambda: "dep-b")
    monkeypatch.setattr(mod, "federate_ingress_active", lambda: True)
    monkeypatch.setattr(mod, "federate_owner_rotate_sec", lambda: 0)
    monkeypatch.setattr(mod, "federate_prefer_local_owner", lambda: False)
    mod._cache_deployment_ids = frozenset({"dep-a", "dep-c"})

    assert mod.federate_group_owner_deployment(123) == "dep-a"
    assert mod.should_process_federate_group_on_current_deployment(124) is True
    assert mod.should_process_federate_group_on_current_deployment(125) is False


def test_federate_group_owner_ring_index_stable_within_epoch():
    assert mod.federate_group_owner_ring_index(733291779, 2, now=100.0, rotate_sec=43200) == (
        mod.federate_group_owner_ring_index(733291779, 2, now=43199.0, rotate_sec=43200)
    )


def test_federate_group_owner_rotates_across_epochs(monkeypatch):
    mod.clear_federate_peer_bot_cache_for_tests()
    monkeypatch.setattr(mod, "load_or_create_deployment_id", lambda: "dep-a")
    monkeypatch.setattr(mod, "federate_owner_rotate_sec", lambda: 43200)
    monkeypatch.setattr(mod, "federate_prefer_local_owner", lambda: False)
    mod._cache_deployment_ids = frozenset({"dep-b"})

    flipped = False
    for gid in range(1, 500):
        a = mod.federate_group_owner_deployment(gid, now=0.0)
        b = mod.federate_group_owner_deployment(gid, now=43200.0)
        if a != b:
            flipped = True
            break
    assert flipped
    assert mod.federate_group_owner_deployment(42, now=0.0) in {"dep-a", "dep-b"}


def test_prefer_local_owner_keeps_capable_local_as_owner(monkeypatch):
    mod.clear_federate_peer_bot_cache_for_tests()
    monkeypatch.setattr(mod, "load_or_create_deployment_id", lambda: "dep-local")
    monkeypatch.setattr(mod, "federate_ingress_active", lambda: True)
    monkeypatch.setattr(mod, "federate_owner_rotate_sec", lambda: 0)
    monkeypatch.setattr(mod, "federate_prefer_local_owner", lambda: True)
    monkeypatch.setattr(
        mod,
        "collect_local_federate_command_capabilities",
        lambda: frozenset({"牛牛帮助"}),
    )
    mod._cache_deployment_ids = frozenset({"dep-peer"})
    mod._cache_deployment_capabilities = {
        "dep-peer": frozenset({"牛牛帮助"}),
    }

    # 无优先时按群号可能落到 peer；开启后本机在环内则固定本机
    assert mod.federate_group_owner_deployment(123, plain="牛牛帮助") == "dep-local"
    assert mod.should_process_federate_group_on_current_deployment(123, plain="牛牛帮助") is True


def test_prefer_local_owner_does_not_steal_incapable_commands(monkeypatch):
    mod.clear_federate_peer_bot_cache_for_tests()
    monkeypatch.setattr(mod, "load_or_create_deployment_id", lambda: "dep-local")
    monkeypatch.setattr(mod, "federate_ingress_active", lambda: True)
    monkeypatch.setattr(mod, "federate_owner_rotate_sec", lambda: 0)
    monkeypatch.setattr(mod, "federate_prefer_local_owner", lambda: True)
    monkeypatch.setattr(
        mod,
        "collect_local_federate_command_capabilities",
        lambda: frozenset({"牛牛帮助"}),
    )
    mod._cache_deployment_ids = frozenset({"dep-peer"})
    mod._cache_deployment_capabilities = {
        "dep-peer": frozenset({"牛牛塔罗牌"}),
    }

    assert mod.federate_group_owner_deployment(733291779, plain="牛牛塔罗牌") == "dep-peer"
    assert mod.should_process_federate_group_on_current_deployment(733291779, plain="牛牛塔罗牌") is False
