from __future__ import annotations

import time

from pallas.core.platform.shard.coord import bot_count as mod


def test_bot_count_plaintext_normalizes_trailing_punctuation() -> None:
    assert mod.normalize_bot_count_command_plaintext("牛牛出列！") == "牛牛出列"
    assert mod.normalize_bot_count_command_plaintext("  牛牛报数!  ") == "牛牛报数"
    assert mod.is_shard_bot_count_command_plaintext("牛牛出列！")


def test_bot_count_coord_plaintext_unifies_claim_key():
    from pallas.core.platform.multi_bot.dedup import cross_bot_group_message_key

    gid, uid, t = 733291779, 2538527601, 1781407061
    key_plain = cross_bot_group_message_key(
        gid,
        uid,
        mod.bot_count_coord_plaintext("牛牛出列"),
        t,
        use_plaintext=True,
        include_message_time=True,
    )
    key_punct = cross_bot_group_message_key(
        gid,
        uid,
        mod.bot_count_coord_plaintext("牛牛出列！"),
        t,
        use_plaintext=True,
        include_message_time=True,
    )
    assert key_plain == key_punct


def test_cross_shard_order_finalize(fake_coord_redis, monkeypatch):
    monkeypatch.setattr(
        "pallas.core.platform.shard.registry.config.get_shard_registry_settings",
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
        "pallas.core.platform.shard.registry.config.get_shard_registry_settings",
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


def test_finalize_absorbs_late_registration_into_order_tail(fake_coord_redis):
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
    assert order == [100, 300]


def test_finalize_keeps_order_when_no_new_registration(fake_coord_redis):
    path = mod._session_path(10086, 999006)
    mod._ensure_session(
        path,
        group_id=10086,
        user_id=1,
        message_time=1,
        seed="2026-05-22:10086",
    )
    mod._register_shard_bots(path, 3, [100, 200])
    data = mod._read_session(path)
    assert data is not None
    data["collect_until"] = time.time() - 0.01
    data["order"] = [100, 200]
    data["finalized_by"] = 100
    mod._write_session_atomic(path, data)
    mod._try_finalize_order(path, 100)
    order = mod._read_session(path).get("order")
    assert isinstance(order, list)
    assert order == [100, 200]


def test_completion_claims_once_after_report_window(fake_coord_redis):
    path = mod._session_path(10086, 999004)
    mod._ensure_session(
        path,
        group_id=10086,
        user_id=1,
        message_time=1,
        seed="2026-05-22:10086",
    )
    data = mod._read_session(path)
    assert data is not None
    data["order"] = [100, 200]
    data["report_until"] = time.time() - 0.01
    mod._write_session_atomic(path, data)

    assert mod._mark_bot_count_reported_and_claim_completion(path, 100)
    assert not mod._mark_bot_count_reported_and_claim_completion(path, 200)

    data = mod._read_session(path)
    assert data is not None
    assert data["reported"] == [100, 200]
    assert data["completion_claimed_by"] == 100


def test_dispatch_progress_does_not_claim_completion_after_report_window(fake_coord_redis):
    path = mod._session_path(10086, 999005)
    mod._ensure_session(
        path,
        group_id=10086,
        user_id=1,
        message_time=1,
        seed="2026-05-22:10086",
    )
    data = mod._read_session(path)
    assert data is not None
    data["order"] = [100, 200]
    data["report_until"] = time.time() - 0.01
    mod._write_session_atomic(path, data)

    assert not mod._mark_bot_count_reported_and_claim_completion(path, 100, allow_timeout=False)
    assert mod._read_session(path).get("completion_claimed_by") is None


async def test_reads_finalized_order_for_local_dispatch(fake_coord_redis):
    from pallas.core.platform.multi_bot.dedup import cross_bot_group_message_key

    group_id, user_id, message_time = 10086, 1, 1
    claim_key = cross_bot_group_message_key(
        group_id,
        user_id,
        mod.bot_count_coord_plaintext("牛牛报数"),
        message_time,
        use_plaintext=True,
        include_message_time=True,
    )
    path = mod._session_path(group_id, claim_key)
    mod._ensure_session(
        path,
        group_id=group_id,
        user_id=user_id,
        message_time=message_time,
        seed="2026-05-22:10086",
    )
    data = mod._read_session(path)
    assert data is not None
    data["order"] = [200, 100]
    mod._write_session_atomic(path, data)

    order = await mod.get_shard_bot_count_order(
        group_id=group_id,
        user_id=user_id,
        plaintext="牛牛报数",
        message_time=message_time,
    )

    assert order == [200, 100]


async def test_repeated_count_does_not_read_previous_completed_session(fake_coord_redis):
    from pallas.core.platform.multi_bot.dedup import cross_bot_group_message_key

    group_id, user_id = 10086, 1
    previous_time, current_time = 100, 200
    previous_key = cross_bot_group_message_key(
        group_id,
        user_id,
        mod.bot_count_coord_plaintext("牛牛报数"),
        previous_time,
        use_plaintext=True,
    )
    previous_path = mod._session_path(group_id, previous_key)
    mod._ensure_session(
        previous_path,
        group_id=group_id,
        user_id=user_id,
        message_time=previous_time,
        seed="2026-05-22:10086",
    )
    data = mod._read_session(previous_path)
    assert data is not None
    data["order"] = [100]
    data["completion_claimed_by"] = 100
    mod._write_session_atomic(previous_path, data)

    order = await mod.get_shard_bot_count_order(
        group_id=group_id,
        user_id=user_id,
        plaintext="牛牛报数",
        message_time=current_time,
    )

    assert order is None


async def test_turn_is_ready_after_previous_bot_reported(fake_coord_redis):
    from pallas.core.platform.multi_bot.dedup import cross_bot_group_message_key

    group_id, user_id, message_time = 10086, 1, 1
    claim_key = cross_bot_group_message_key(
        group_id,
        user_id,
        mod.bot_count_coord_plaintext("牛牛报数"),
        message_time,
        use_plaintext=True,
        include_message_time=True,
    )
    path = mod._session_path(group_id, claim_key)
    mod._ensure_session(
        path,
        group_id=group_id,
        user_id=user_id,
        message_time=message_time,
        seed="2026-05-22:10086",
    )
    data = mod._read_session(path)
    assert data is not None
    data["order"] = [100, 200]
    data["reported"] = [100]
    mod._write_session_atomic(path, data)

    assert await mod.wait_shard_bot_count_turn(
        group_id=group_id,
        user_id=user_id,
        plaintext="牛牛报数",
        message_time=message_time,
        bot_id=200,
        allow_timeout=False,
    )


def test_late_shard_does_not_extend_collect_window(fake_coord_redis):
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
    assert second_until == first_until


async def test_wait_for_order_finalizes_for_non_min_coordinator(fake_coord_redis):
    """unified 模式协调任务持有者未必是已登记最小牛，仍须能完成 finalize。"""
    path = mod._session_path(10086, 999007)
    mod._ensure_session(
        path,
        group_id=10086,
        user_id=1,
        message_time=1,
        seed="2026-05-22:10086",
    )
    mod._register_shard_bots(path, 0, [300, 100, 200])
    data = mod._read_session(path)
    assert data is not None
    data["collect_until"] = time.time() - 0.01
    mod._write_session_atomic(path, data)

    order = await mod._wait_for_order(path, deadline=time.time() + 5.0, self_bot_id=200)
    assert order is not None
    assert set(order) == {100, 200, 300}


async def test_coordinator_cancels_when_cooldown_active(fake_coord_redis, monkeypatch):
    class FakeGroupConfig:
        def __init__(self, group_id: int, cooldown: int) -> None:
            self.group_id = group_id
            self.cooldown = cooldown

        async def is_cooldown(self, action_type: str) -> bool:
            return False

        async def refresh_cooldown(self, action_type: str) -> None:
            return None

    monkeypatch.setattr(
        "pallas.core.platform.shard.registry.config.get_shard_registry_settings",
        lambda: type("S", (), {"shard_id": 0})(),
    )
    monkeypatch.setattr("pallas.core.foundation.config.GroupConfig", FakeGroupConfig)

    from pallas.core.platform.multi_bot.dedup import cross_bot_group_message_key

    group_id, user_id, message_time = 10086, 1, 1
    claim_key = cross_bot_group_message_key(
        group_id,
        user_id,
        mod.bot_count_coord_plaintext("牛牛报数"),
        message_time,
        use_plaintext=True,
        include_message_time=True,
    )
    path = mod._session_path(group_id, claim_key)
    mod._ensure_session(
        path,
        group_id=group_id,
        user_id=user_id,
        message_time=message_time,
        seed="2026-05-22:10086",
    )
    mod._register_shard_bots(path, 0, [100])
    data = mod._read_session(path)
    assert data is not None
    data["collect_until"] = time.time() - 0.01
    mod._write_session_atomic(path, data)

    result = await mod.run_shard_coordinated_bot_count(
        group_id=group_id,
        user_id=user_id,
        plaintext="牛牛报数",
        message_time=message_time,
        self_bot_id=100,
    )
    assert result is None
    assert mod._read_session(path)["cancelled"] is True
