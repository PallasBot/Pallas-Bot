from __future__ import annotations

import pytest

from pallas.core.platform.shard import presence_health as h


@pytest.fixture(autouse=True)
def _reset_health() -> None:
    h.reset_presence_health_state_for_tests()
    yield
    h.reset_presence_health_state_for_tests()


def test_evaluate_get_status_payload_online_good() -> None:
    assert h.evaluate_get_status_healthy({"online": True, "good": True}) is True
    assert h.evaluate_get_status_healthy({"online": False, "good": True}) is False
    assert h.evaluate_get_status_healthy({"online": True, "good": False}) is False
    assert h.evaluate_get_status_healthy({"online": True}) is True
    assert h.evaluate_get_status_healthy({"good": True}) is True
    assert h.evaluate_get_status_healthy(None) is False
    assert h.evaluate_get_status_healthy({}) is False


def test_record_probe_kicks_after_threshold(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(h, "STATUS_FAIL_THRESHOLD", 3)
    assert h.record_health_probe_result(111, ok=False) is False
    assert h.record_health_probe_result(111, ok=False) is False
    assert 111 not in h.health_quarantine_qq_ids()
    assert h.record_health_probe_result(111, ok=False) is True
    assert 111 in h.health_quarantine_qq_ids()
    assert h.record_health_probe_result(111, ok=True) is False
    assert 111 not in h.health_quarantine_qq_ids()


@pytest.mark.asyncio
async def test_apply_probes_kicks_and_disconnects(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(h, "STATUS_FAIL_THRESHOLD", 2)
    monkeypatch.setattr(h, "STATUS_PROBE_MIN_INTERVAL_SEC", 0)
    disconnected: list[int] = []
    closed: list[int] = []

    class _Bot:
        self_id = "222"

        async def call_api(self, api: str):
            assert api == "get_status"
            raise TimeoutError("zombie")

    async def fake_close(qq: int) -> bool:
        closed.append(int(qq))
        return True

    monkeypatch.setattr(
        "pallas.core.platform.shard.context.sharding_active",
        lambda: True,
    )
    monkeypatch.setattr("nonebot.get_bots", lambda: {"222": _Bot()})
    monkeypatch.setattr(
        "pallas.core.platform.shard.presence.note_worker_bot_disconnected_sync",
        lambda *, qq: disconnected.append(int(qq)),
    )
    monkeypatch.setattr(
        "pallas.core.platform.shard.presence.close_local_bot_connection",
        fake_close,
    )

    assert await h.apply_presence_qq_health_probes(force=True) == []
    kicked = await h.apply_presence_qq_health_probes(force=True)
    assert kicked == [222]
    assert disconnected == [222]
    assert closed == [222]
    assert 222 in h.health_quarantine_qq_ids()


def test_bot_has_cluster_connection_false_when_quarantined(monkeypatch: pytest.MonkeyPatch) -> None:
    from pallas.core.platform.shard import presence as presence_mod

    h.record_health_probe_result(100, ok=False)
    h.record_health_probe_result(100, ok=False)
    h.record_health_probe_result(100, ok=False)
    assert 100 in h.health_quarantine_qq_ids()

    monkeypatch.setattr(presence_mod, "bot_has_local_connection", lambda qq: qq == 100)
    monkeypatch.setattr(presence_mod.shard_ctx, "sharding_active", lambda: True)
    monkeypatch.setattr(presence_mod, "get_cluster_online_bot_ids", lambda: frozenset({100}))
    assert presence_mod.bot_has_cluster_connection(100) is False


@pytest.mark.asyncio
async def test_on_bot_connect_closes_unhealthy_quarantined_reconnect(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from pallas.core.platform.multi_bot import connected_roster as roster

    closed: list[int] = []
    h.record_health_probe_result(444, ok=False)
    h.record_health_probe_result(444, ok=False)
    h.record_health_probe_result(444, ok=False)
    assert 444 in h.health_quarantine_qq_ids()

    class _Bot:
        self_id = "444"
        type = "OneBot V11"

        async def call_api(self, api: str):
            assert api == "get_status"
            return {"online": False}

    async def fake_close(qq: int) -> bool:
        closed.append(int(qq))
        return True

    monkeypatch.setattr(
        "pallas.core.platform.shard.presence.close_local_bot_connection",
        fake_close,
    )
    await roster.on_bot_connect(_Bot())  # type: ignore[arg-type]
    assert closed == [444]
    assert 444 in h.health_quarantine_qq_ids()
    assert 444 not in roster.connected_bot_ids()


@pytest.mark.asyncio
async def test_apply_probes_respects_min_interval(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(h, "STATUS_PROBE_MIN_INTERVAL_SEC", 60.0)
    calls = {"n": 0}

    class _Bot:
        self_id = "333"

        async def call_api(self, api: str):
            calls["n"] += 1
            return {"online": True, "good": True}

    monkeypatch.setattr(
        "pallas.core.platform.shard.context.sharding_active",
        lambda: True,
    )
    monkeypatch.setattr("nonebot.get_bots", lambda: {"333": _Bot()})

    await h.apply_presence_qq_health_probes(force=True)
    assert calls["n"] == 1
    await h.apply_presence_qq_health_probes()
    assert calls["n"] == 1
