from __future__ import annotations

import time

from src.platform.shard.coord import bot_count as mod


def test_fanout_plaintext(monkeypatch):
    from src.platform.ingress.config import clear_ingress_fanout_config_cache

    monkeypatch.setattr(
        "src.platform.ingress.config._ingress_env_str",
        lambda name, default="": "牛牛,帕拉斯,牛牛报数,牛牛出列"
        if name == "PALLAS_INGRESS_FANOUT_GREETING"
        else default,
    )
    clear_ingress_fanout_config_cache()
    assert mod.is_bot_count_fanout_plaintext("牛牛报数")
    assert mod.is_bot_count_fanout_plaintext("牛牛出列")
    assert mod.is_bot_count_fanout_plaintext("牛牛出列！")
    assert not mod.is_bot_count_fanout_plaintext("牛牛喝酒")


def test_bot_count_plaintext_normalizes_trailing_punctuation(monkeypatch):
    monkeypatch.setattr("src.platform.shard.registry.config.is_sharding_active", lambda: True)
    assert mod.normalize_bot_count_command_plaintext("牛牛出列！") == "牛牛出列"
    assert mod.normalize_bot_count_command_plaintext("  牛牛报数!  ") == "牛牛报数"
    assert mod.is_shard_bot_count_command_plaintext("牛牛出列！")
    assert mod.should_skip_ingress_claim_for_shard_bot_count("牛牛出列！")


def test_bot_count_coord_plaintext_unifies_claim_key():
    from src.platform.multi_bot.dedup import cross_bot_group_message_key

    gid, uid, t = 733291779, 2538527601, 1781407061
    key_plain = cross_bot_group_message_key(
        gid,
        uid,
        mod.bot_count_coord_plaintext("牛牛出列"),
        t,
        use_plaintext=True,
    )
    key_punct = cross_bot_group_message_key(
        gid,
        uid,
        mod.bot_count_coord_plaintext("牛牛出列！"),
        t,
        use_plaintext=True,
    )
    assert key_plain == key_punct


def test_bot_count_ingress_fanout_without_greeting_whitelist(monkeypatch):
    from src.platform.ingress.config import clear_ingress_fanout_config_cache

    monkeypatch.setattr("src.platform.shard.registry.config.is_sharding_active", lambda: True)
    monkeypatch.setattr(
        "src.platform.ingress.config._ingress_env_str",
        lambda name, default="": "牛牛,帕拉斯,牛牛赞我,赞我"
        if name == "PALLAS_INGRESS_FANOUT_GREETING"
        else default,
    )
    clear_ingress_fanout_config_cache()
    assert mod.should_skip_ingress_claim_for_shard_bot_count("牛牛报数")
    assert mod.is_bot_count_fanout_plaintext("牛牛报数")
    assert not mod.is_bot_count_fanout_plaintext("牛牛赞我")


def test_cross_shard_order_finalize(fake_coord_redis, monkeypatch):
    monkeypatch.setattr(
        "src.platform.shard.registry.config.get_shard_registry_settings",
        lambda: type("S", (), {"shard_id": 0})(),
    )

    path = mod._session_path(10086, 999001)
    mod._ensure_session(
        path,
        group_id=10086,
        user_id=1,
        message_time=1,
        seed="2026-05-21:10086",
    )
    mod._register_shard_bots(path, 0, [300, 100])
    monkeypatch.setattr(
        "src.platform.shard.registry.config.get_shard_registry_settings",
        lambda: type("S", (), {"shard_id": 1})(),
    )
    mod._register_shard_bots(path, 1, [200])

    data = mod._read_session(path)
    assert data is not None
    data["collect_until"] = time.time() - 0.01
    mod._write_session_atomic(path, data)

    mod._try_finalize_order(path, 100)
    order = mod._read_session(path).get("order")
    assert isinstance(order, list)
    assert set(order) == {100, 200, 300}
    assert len(order) == 3


def test_finalize_reopens_order_when_registration_grows(fake_coord_redis):
    path = mod._session_path(10086, 999003)
    mod._ensure_session(
        path,
        group_id=10086,
        user_id=1,
        message_time=1,
        seed="2026-05-22:10086",
    )
    mod._register_shard_bots(path, 3, [100])
    data = mod._read_session(path)
    assert data is not None
    data["collect_until"] = time.time() - 0.01
    data["order"] = [100]
    data["finalized_by"] = 100
    mod._write_session_atomic(path, data)
    mod._register_shard_bots(path, 5, [300])
    data = mod._read_session(path)
    assert data is not None
    data["collect_until"] = time.time() - 0.01
    mod._write_session_atomic(path, data)
    mod._try_finalize_order(path, 100)
    order = mod._read_session(path).get("order")
    assert isinstance(order, list)
    assert set(order) == {100, 300}


def test_non_min_bot_can_rebuild_stale_order_after_registration_grows(fake_coord_redis):
    path = mod._session_path(10086, 999004)
    mod._ensure_session(
        path,
        group_id=10086,
        user_id=1,
        message_time=1,
        seed="2026-05-22:10086",
    )
    mod._register_shard_bots(path, 1, [100])
    data = mod._read_session(path)
    assert data is not None
    data["collect_until"] = time.time() - 0.01
    data["order"] = [100]
    data["finalized_by"] = 100
    mod._write_session_atomic(path, data)

    mod._register_shard_bots(path, 2, [300])
    data = mod._read_session(path)
    assert data is not None
    data["collect_until"] = time.time() - 0.01
    mod._write_session_atomic(path, data)

    mod._try_finalize_order(path, 300)
    data = mod._read_session(path)
    assert data is not None
    assert isinstance(data.get("order"), list)
    assert set(data["order"]) == {100, 300}
    assert data["finalized_by"] == 300


def test_non_min_bot_does_not_clear_stale_order_without_rebuilding(fake_coord_redis):
    path = mod._session_path(10086, 999005)
    mod._ensure_session(
        path,
        group_id=10086,
        user_id=1,
        message_time=1,
        seed="2026-05-22:10086",
    )
    mod._register_shard_bots(path, 1, [100, 200])
    data = mod._read_session(path)
    assert data is not None
    data["collect_until"] = time.time() - 0.01
    data["order"] = [100]
    data["finalized_by"] = 100
    mod._write_session_atomic(path, data)

    mod._try_finalize_order(path, 200)
    data = mod._read_session(path)
    assert data is not None
    assert isinstance(data.get("order"), list)
    assert set(data["order"]) == {100, 200}


def test_late_shard_extends_collect_window(fake_coord_redis):
    path = mod._session_path(10086, 999002)
    mod._ensure_session(
        path,
        group_id=10086,
        user_id=1,
        message_time=1,
        seed="2026-05-22:10086",
    )
    first_until = float(mod._read_session(path)["collect_until"])
    time.sleep(0.05)
    mod._register_shard_bots(path, 1, [200])
    second_until = float(mod._read_session(path)["collect_until"])
    assert second_until >= first_until
