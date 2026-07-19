import json

from pallas.core.platform.shard.registry.store import TEST_SHARD_ROLE, ShardRecord, ShardRegistry
from pallas.core.platform.shard.registry.worker_count import calc_production_worker_count


def test_count_from_ws_url_port(tmp_path):
    accounts = tmp_path / "accounts.json"
    accounts.write_text(
        json.dumps({
            "727130160": {
                "qq": "727130160",
                "enabled": True,
                "ws_url": "ws://172.17.0.1:7977/onebot/v11/ws",
            }
        }),
        encoding="utf-8",
    )
    reg = ShardRegistry(bots_per_shard=5, worker_base_port=7970, ws_host="127.0.0.1")
    assert (
        calc_production_worker_count(
            bots_per_shard=5,
            accounts_path=accounts,
            registry=reg,
        )
        == 8
    )


def test_enabled_count_not_less_than_ws_hint(tmp_path):
    accounts = tmp_path / "accounts.json"
    items = {str(i): {"qq": str(i), "enabled": True, "ws_url": "ws://127.0.0.1:7970/onebot/v11/ws"} for i in range(35)}
    items["727130160"] = {
        "qq": "727130160",
        "enabled": True,
        "ws_url": "ws://172.17.0.1:7977/onebot/v11/ws",
    }
    accounts.write_text(json.dumps(items), encoding="utf-8")
    reg = ShardRegistry(bots_per_shard=5, worker_base_port=7970, ws_host="127.0.0.1")
    assert calc_production_worker_count(accounts_path=accounts, registry=reg) == 8


def test_dual_test_shards_do_not_inflate_worker_count():
    reg = ShardRegistry(
        bots_per_shard=5,
        worker_base_port=7970,
        ws_host="127.0.0.1",
        shards=[ShardRecord(id=i, port=7970 + i, role="normal", bot_ids=[str(i)]) for i in range(8)]
        + [
            ShardRecord(id=98, port=7979, role=TEST_SHARD_ROLE, bot_ids=["1823196773"]),
            ShardRecord(id=99, port=7978, role=TEST_SHARD_ROLE, bot_ids=["3831667476"]),
        ],
        assignments={
            **{str(1000 + i): i for i in range(8)},
            "1823196773": 98,
            "3831667476": 99,
        },
    )
    assert calc_production_worker_count(registry=reg) == 8


def test_test_account_ws_url_does_not_inflate_worker_count(tmp_path):
    accounts = tmp_path / "accounts.json"
    items = {
        str(1000 + i): {
            "qq": str(1000 + i),
            "enabled": True,
            "ws_url": f"ws://172.17.0.1:{7970 + i}/onebot/v11/ws",
        }
        for i in range(9)
    }
    items["1823196773"] = {
        "qq": "1823196773",
        "enabled": True,
        "ws_url": "ws://172.17.0.1:7979/onebot/v11/ws",
    }
    accounts.write_text(json.dumps(items), encoding="utf-8")
    reg = ShardRegistry(
        bots_per_shard=5,
        worker_base_port=7970,
        ws_host="127.0.0.1",
        shards=[ShardRecord(id=i, port=7970 + i, role="normal", bot_ids=[]) for i in range(9)]
        + [ShardRecord(id=98, port=7979, role=TEST_SHARD_ROLE, bot_ids=["1823196773"])],
        assignments={**{str(1000 + i): i for i in range(9)}, "1823196773": 98},
    )
    assert calc_production_worker_count(accounts_path=accounts, registry=reg) == 9
