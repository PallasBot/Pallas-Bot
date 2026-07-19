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

    class _Bot:
        self_id = "222"

        async def call_api(self, api: str):
            assert api == "get_status"
            raise TimeoutError("zombie")

    monkeypatch.setattr(
        "pallas.core.platform.shard.context.sharding_active",
        lambda: True,
    )
    monkeypatch.setattr("nonebot.get_bots", lambda: {"222": _Bot()})
    monkeypatch.setattr(
        "pallas.core.platform.shard.presence.note_worker_bot_disconnected_sync",
        lambda *, qq: disconnected.append(int(qq)),
    )

    assert await h.apply_presence_qq_health_probes(force=True) == []
    kicked = await h.apply_presence_qq_health_probes(force=True)
    assert kicked == [222]
    assert disconnected == [222]
    assert 222 in h.health_quarantine_qq_ids()


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
