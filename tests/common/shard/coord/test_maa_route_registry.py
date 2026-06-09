from src.platform.shard.coord import maa_route_registry as reg


def test_register_and_resolve_user_route(fake_coord_redis, monkeypatch) -> None:
    monkeypatch.setattr(reg, "is_sharding_active", lambda: True)
    monkeypatch.setattr(
        reg,
        "get_shard_registry_settings",
        lambda: type("S", (), {"role": "worker", "shard_id": 1})(),
    )
    monkeypatch.setattr(reg, "worker_port_for_shard", lambda _sid: 8091)

    reg.register_maa_user_route("123456789", worker_port=8091)
    assert reg.resolve_worker_port_for_maa_user("123456789") == 8091
    key = reg._route_redis_key("123456789")
    assert key is not None
    assert key in fake_coord_redis[0]


def test_resolve_worker_port_falls_back_to_shard_registry(fake_coord_redis, monkeypatch) -> None:
    monkeypatch.setattr(reg, "is_sharding_active", lambda: True)

    class _Reg:
        def shard_for_bot(self, bot_id: str):
            return 1 if bot_id == "123456789" else None

    monkeypatch.setattr(reg, "get_shard_registry", lambda: _Reg())
    monkeypatch.setattr(reg, "worker_port_for_shard", lambda sid, registry=None: 8091 if sid == 1 else 8090)

    assert reg.resolve_worker_port_for_maa_user("123456789") == 8091
    assert reg.resolve_worker_port_for_maa_user("999999999") is None
