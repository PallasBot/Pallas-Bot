from __future__ import annotations

import asyncio
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
    assert data["present_group_ids"] == []
    assert client.set.call_args.kwargs["ex"] > 0


def test_peer_roster_publishes_and_reads_deployment_status(monkeypatch):
    client = MagicMock()
    client.scan_iter.return_value = iter([
        b"pallas:fed:pool-1:peer_bots:dep-local",
        b"pallas:fed:pool-1:peer_bots:dep-b",
    ])
    client.get.side_effect = lambda key: {
        "pallas:fed:pool-1:peer_bots:dep-b": json.dumps({
            "deployment_id": "dep-b",
            "deployment_name": "部署 B",
            "bot_ids": [20001, 20002, 20003],
            "online_bot_ids": [20001, 20002, 20003],
            "public_bot_ids": [20001, 20002],
            "public_online_bot_names": {"20001": "对端一号", "20003": "不应公开"},
        }),
    }.get(key.decode("utf-8") if isinstance(key, bytes) else key)
    monkeypatch.setattr(mod, "get_federate_redis_client", lambda: client)
    monkeypatch.setattr(mod, "federate_redis_prefix", lambda _cfg=None: "pallas:fed:pool-1")
    monkeypatch.setattr(mod, "load_or_create_deployment_id", lambda: "dep-local")
    monkeypatch.setattr(mod, "get_catalog_bot_ids", lambda: frozenset({10001}))
    monkeypatch.setattr(mod, "collect_local_federate_online_bot_ids", lambda: frozenset({10001}))
    monkeypatch.setattr(mod, "local_federate_deployment_name", lambda: "部署 A")
    monkeypatch.setattr(
        mod,
        "collect_local_federate_public_online_bot_names",
        lambda _online_ids, _public_bot_ids: {10001: "本机一号"},
    )

    assert mod.publish_local_federate_peer_bot_ids_sync(public_bot_ids=frozenset({10001})) is True
    _, payload = client.set.call_args.args[:2]
    assert json.loads(payload) == {
        "deployment_id": "dep-local",
        "deployment_name": "部署 A",
        "bot_ids": [10001],
        "online_bot_ids": [10001],
        "public_bot_ids": [10001],
        "public_online_bot_names": {"10001": "本机一号"},
        "updated_at": json.loads(payload)["updated_at"],
        "present_group_ids": [],
        "command_capability_protocol": mod.COMMAND_CAPABILITY_PROTOCOL_VERSION,
    }

    mod.refresh_federate_peer_bot_ids_sync()
    peer = mod.get_federate_peer_bot_roster("dep-b")
    assert peer is not None
    assert peer.deployment_name == "部署 B"
    assert peer.online_bot_ids == frozenset({20001, 20002, 20003})
    assert peer.public_bot_ids == frozenset({20001, 20002})
    assert peer.public_online_bot_names == {20001: "对端一号"}

    from pallas.api.platform import get_federate_peer_bot_rosters

    assert get_federate_peer_bot_rosters() == (peer,)


def test_peer_roster_marks_legacy_online_status_unknown(monkeypatch):
    client = MagicMock()
    client.scan_iter.return_value = iter([b"pallas:fed:pool-1:peer_bots:dep-legacy"])
    client.get.return_value = json.dumps({"deployment_id": "dep-legacy", "bot_ids": [20001]})
    monkeypatch.setattr(mod, "get_federate_redis_client", lambda: client)
    monkeypatch.setattr(mod, "federate_redis_prefix", lambda _cfg=None: "pallas:fed:pool-1")
    monkeypatch.setattr(mod, "load_or_create_deployment_id", lambda: "dep-local")

    mod.refresh_federate_peer_bot_ids_sync()

    peer = mod.get_federate_peer_bot_roster("dep-legacy")
    assert peer is not None
    assert peer.online_bot_ids is None
    assert peer.public_online_bot_names == {}


def test_federate_bot_rosters_include_local_deployment(monkeypatch):
    mod.clear_federate_peer_bot_cache_for_tests()
    monkeypatch.setattr(mod, "load_or_create_deployment_id", lambda: "dep-local")
    monkeypatch.setattr(mod, "local_federate_deployment_name", lambda: "部署 A")
    monkeypatch.setattr(mod, "get_catalog_bot_ids", lambda: frozenset({10001, 10002}))
    monkeypatch.setattr(mod, "collect_local_federate_online_bot_ids", lambda: frozenset({10002}))

    async def public_ids(_bot_ids):
        return frozenset({10001})

    monkeypatch.setattr(mod, "collect_local_federate_public_bot_ids", public_ids)
    monkeypatch.setattr(
        mod,
        "collect_local_federate_public_online_bot_names",
        lambda _online_ids, _public_bot_ids: {10002: "本机二号"},
    )

    rosters = asyncio.run(mod.get_federate_bot_rosters())

    assert rosters == (
        mod.FederatePeerBotRoster(
            deployment_id="dep-local",
            deployment_name="部署 A",
            bot_ids=frozenset({10001, 10002}),
            online_bot_ids=frozenset({10002}),
            public_bot_ids=frozenset({10001}),
            public_online_bot_names={},
        ),
    )


def test_refresh_federate_peer_bot_ids_sync_reads_other_deployments(monkeypatch):
    client = MagicMock()
    client.scan_iter.return_value = iter([
        b"pallas:fed:pool-1:peer_bots:dep-local",
        b"pallas:fed:pool-1:peer_bots:dep-a",
        b"pallas:fed:pool-1:peer_bots:dep-b",
    ])
    client.get.side_effect = lambda key: {
        "pallas:fed:pool-1:peer_bots:dep-local": json.dumps({"bot_ids": [111]}),
        "pallas:fed:pool-1:peer_bots:dep-a": json.dumps({"bot_ids": [222, 333], "command_capabilities": ["牛牛帮助"]}),
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


def test_owner_ring_prefers_explicit_caps_over_undeclared_legacy_peers(monkeypatch):
    """本机（或任一端）已显式宣告能处理时，未宣告能力的旧对端不再抢归属。"""
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

    assert mod.federate_group_owner_deployment(123, plain="牛牛塔罗牌") == "dep-b"
    assert mod.should_process_federate_group_on_current_deployment(123, plain="牛牛塔罗牌") is True
    assert mod.should_process_federate_group_on_current_deployment(124, plain="牛牛塔罗牌") is True


def test_owner_ring_custom_prefix_not_stolen_by_generic_sing_peer(monkeypatch):
    """自定义前缀（如一歌唱歌）只在宣告了该前缀的部署间归属，不被仅有牛牛唱歌的对端夺走。"""
    mod.clear_federate_peer_bot_cache_for_tests()
    monkeypatch.setattr(mod, "load_or_create_deployment_id", lambda: "dep-local")
    monkeypatch.setattr(mod, "federate_ingress_active", lambda: True)
    monkeypatch.setattr(mod, "federate_owner_rotate_sec", lambda: 0)
    monkeypatch.setattr(mod, "federate_prefer_local_owner", lambda: False)
    monkeypatch.setattr(
        mod,
        "collect_local_federate_command_capabilities",
        lambda: frozenset({"一歌唱歌", "一歌点歌", "牛牛唱歌"}),
    )
    mod._cache_deployment_ids = frozenset({"dep-peer"})
    mod._cache_deployment_capabilities = {
        "dep-peer": frozenset({"牛牛唱歌", "牛牛点歌"}),
    }

    for gid in (1085338862, 733291779, 1, 2, 99):
        assert mod.federate_group_owner_deployment(gid, plain="一歌唱歌 ファイター") == "dep-local"
        assert mod.should_process_federate_group_on_current_deployment(gid, plain="一歌唱歌 ファイター")


def test_owner_ring_falls_back_to_legacy_when_nobody_explicitly_covers(monkeypatch):
    """无人显式覆盖该命令时，未宣告能力的对端仍可进环（兼容旧端闲聊/未知命令）。"""
    mod.clear_federate_peer_bot_cache_for_tests()
    monkeypatch.setattr(mod, "load_or_create_deployment_id", lambda: "dep-b")
    monkeypatch.setattr(mod, "federate_ingress_active", lambda: True)
    monkeypatch.setattr(mod, "federate_owner_rotate_sec", lambda: 0)
    monkeypatch.setattr(mod, "federate_prefer_local_owner", lambda: False)
    monkeypatch.setattr(mod, "collect_local_federate_command_capabilities", lambda: frozenset({"牛牛帮助"}))
    mod._cache_deployment_ids = frozenset({"dep-a", "dep-c"})
    mod._cache_deployment_capabilities = {
        "dep-a": None,
        "dep-c": None,
    }

    # 本机未宣告「随便聊聊」；旧对端未宣告 → 退回全员环，123%3==0 → dep-a
    assert mod.federate_group_owner_deployment(123, plain="随便聊聊") == "dep-a"


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


def test_yield_federate_when_peer_covers_command_local_does_not(monkeypatch):
    """本机无决斗等能力、对端显式有时，即使本机不认作命令也不得参与抢占。"""
    mod.clear_federate_peer_bot_cache_for_tests()
    monkeypatch.setattr(mod, "load_or_create_deployment_id", lambda: "dep-local")
    monkeypatch.setattr(mod, "federate_ingress_active", lambda: True)
    monkeypatch.setattr(
        mod,
        "collect_local_federate_command_capabilities",
        lambda: frozenset({"牛牛帮助"}),
    )
    mod._cache_deployment_ids = frozenset({"dep-peer"})
    mod._cache_deployment_capabilities = {
        "dep-peer": frozenset({"牛牛决斗", "八角笼牛"}),
    }
    mod._cache_deployment_present_groups = {
        "dep-peer": frozenset({1076683542}),
    }

    assert mod.should_yield_federate_ingress_for_peer_command(1076683542, plain="牛牛决斗") is True
    assert mod.should_yield_federate_ingress_for_peer_command(1076683542, plain="牛牛帮助") is False
    assert mod.should_yield_federate_ingress_for_peer_command(1076683542, plain="今天吃什么") is False


def test_yield_federate_skips_when_capable_peer_not_present_in_group(monkeypatch):
    mod.clear_federate_peer_bot_cache_for_tests()
    monkeypatch.setattr(mod, "load_or_create_deployment_id", lambda: "dep-local")
    monkeypatch.setattr(mod, "federate_ingress_active", lambda: True)
    monkeypatch.setattr(
        mod,
        "collect_local_federate_command_capabilities",
        lambda: frozenset({"牛牛帮助"}),
    )
    mod._cache_deployment_ids = frozenset({"dep-peer"})
    mod._cache_deployment_capabilities = {
        "dep-peer": frozenset({"牛牛决斗"}),
    }
    mod._cache_deployment_present_groups = {
        "dep-peer": frozenset({999}),
    }

    assert mod.should_yield_federate_ingress_for_peer_command(1076683542, plain="牛牛决斗") is False


def test_owner_ring_excludes_peer_not_present_in_group(monkeypatch):
    """对端宣告了在场群且不含本群时，不参与命令归属（避免空应答）。"""
    mod.clear_federate_peer_bot_cache_for_tests()
    monkeypatch.setattr(mod, "load_or_create_deployment_id", lambda: "dep-local")
    monkeypatch.setattr(mod, "federate_ingress_active", lambda: True)
    monkeypatch.setattr(mod, "federate_owner_rotate_sec", lambda: 0)
    monkeypatch.setattr(mod, "federate_prefer_local_owner", lambda: False)
    monkeypatch.setattr(
        mod,
        "collect_local_federate_command_capabilities",
        lambda: frozenset({"牛牛喝酒"}),
    )
    mod._cache_deployment_ids = frozenset({"dep-peer"})
    mod._cache_deployment_capabilities = {
        "dep-peer": frozenset({"牛牛喝酒"}),
    }
    mod._cache_deployment_present_groups = {
        "dep-peer": frozenset({999}),  # 不在 733291779
    }

    assert mod.federate_group_owner_deployment(733291779, plain="牛牛喝酒") == "dep-local"
    assert mod.should_process_federate_group_on_current_deployment(733291779, plain="牛牛喝酒") is True


def test_owner_ring_keeps_legacy_peer_without_present_groups_field(monkeypatch):
    """未宣告 present_group_ids 的对端仍视为可能在场。"""
    mod.clear_federate_peer_bot_cache_for_tests()
    monkeypatch.setattr(mod, "load_or_create_deployment_id", lambda: "dep-b")
    monkeypatch.setattr(mod, "federate_ingress_active", lambda: True)
    monkeypatch.setattr(mod, "federate_owner_rotate_sec", lambda: 0)
    monkeypatch.setattr(mod, "federate_prefer_local_owner", lambda: False)
    monkeypatch.setattr(
        mod,
        "collect_local_federate_command_capabilities",
        lambda: frozenset({"牛牛喝酒"}),
    )
    mod._cache_deployment_ids = frozenset({"dep-a"})
    mod._cache_deployment_capabilities = {"dep-a": frozenset({"牛牛喝酒"})}
    mod._cache_deployment_present_groups = {"dep-a": None}

    # rotate_sec=0：ring=[dep-a, dep-b]，122%2==0 → dep-a
    assert mod.federate_group_owner_deployment(122, plain="牛牛喝酒") == "dep-a"
    assert mod.should_process_federate_group_on_current_deployment(122, plain="牛牛喝酒") is False


def test_publish_includes_present_group_ids(monkeypatch):
    client = MagicMock()
    monkeypatch.setattr(mod, "get_federate_redis_client", lambda: client)
    monkeypatch.setattr(mod, "federate_redis_prefix", lambda _cfg=None: "pallas:fed:pool-1")
    monkeypatch.setattr(mod, "load_or_create_deployment_id", lambda: "dep-local")
    monkeypatch.setattr(mod, "get_catalog_bot_ids", lambda: frozenset({111}))
    monkeypatch.setattr(mod, "collect_local_federate_command_capabilities", lambda: frozenset({"牛牛帮助"}))
    monkeypatch.setattr(mod, "collect_local_present_group_ids", lambda: [42, 733291779])

    assert mod.publish_local_federate_peer_bot_ids_sync() is True
    data = json.loads(client.set.call_args.args[1])
    assert data["present_group_ids"] == [42, 733291779]
    assert data["command_capability_protocol"] == mod.COMMAND_CAPABILITY_PROTOCOL_VERSION
    assert data["command_capabilities"] == ["牛牛帮助"]


def test_refresh_reads_present_group_ids(monkeypatch):
    client = MagicMock()
    client.scan_iter.return_value = iter([b"pallas:fed:pool-1:peer_bots:dep-peer"])
    client.get.side_effect = lambda key: json.dumps({
        "deployment_id": "dep-peer",
        "bot_ids": [222],
        "present_group_ids": [733291779],
        "command_capability_protocol": mod.COMMAND_CAPABILITY_PROTOCOL_VERSION,
        "command_capabilities": ["牛牛喝酒"],
    })
    monkeypatch.setattr(mod, "get_federate_redis_client", lambda: client)
    monkeypatch.setattr(mod, "federate_redis_prefix", lambda _cfg=None: "pallas:fed:pool-1")
    monkeypatch.setattr(mod, "load_or_create_deployment_id", lambda: "dep-local")

    mod.refresh_federate_peer_bot_ids_sync()
    assert mod.get_federate_peer_present_groups("dep-peer") == frozenset({733291779})
    assert mod.get_federate_peer_command_capability_protocol("dep-peer") == mod.COMMAND_CAPABILITY_PROTOCOL_VERSION


def test_refresh_marks_peer_without_capability_protocol_as_incompatible(monkeypatch):
    client = MagicMock()
    client.scan_iter.return_value = iter([b"pallas:fed:pool-1:peer_bots:dep-peer"])
    client.get.return_value = json.dumps({
        "deployment_id": "dep-peer",
        "bot_ids": [222],
        "command_capabilities": ["soyo唱歌"],
    })
    monkeypatch.setattr(mod, "get_federate_redis_client", lambda: client)
    monkeypatch.setattr(mod, "federate_redis_prefix", lambda _cfg=None: "pallas:fed:pool-1")
    monkeypatch.setattr(mod, "load_or_create_deployment_id", lambda: "dep-local")

    mod.refresh_federate_peer_bot_ids_sync()

    assert mod.get_federate_peer_command_capability_protocol("dep-peer") is None
    assert mod.get_incompatible_federate_command_capability_peers() == ("dep-peer",)


def test_collect_local_federate_command_capabilities_includes_explicit_command_prefixes(
    monkeypatch,
):
    """音频映射等写入的 extra.command_prefixes 必须进入协同能力宣告。"""
    from types import SimpleNamespace

    fake_plugins = [
        SimpleNamespace(
            metadata=SimpleNamespace(
                extra={
                    "command_prefixes": ["一歌唱歌", "一歌点歌", "咲希唱歌"],
                    "menu_data": [{"trigger_condition": "牛牛唱歌 歌曲名"}],
                }
            )
        ),
        SimpleNamespace(
            metadata=SimpleNamespace(
                extra={
                    "exact_plaintexts": ["牛牛在吗"],
                    "menu_data": [],
                }
            )
        ),
    ]
    # peer_bots 内 from nonebot import get_loaded_plugins；patch nonebot 模块
    import nonebot

    monkeypatch.setattr(nonebot, "get_loaded_plugins", lambda: fake_plugins)

    caps = mod.collect_local_federate_command_capabilities()
    assert "一歌唱歌" in caps
    assert "一歌点歌" in caps
    assert "咲希唱歌" in caps
    assert "牛牛唱歌" in caps
    assert "牛牛在吗" in caps
