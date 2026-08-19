import asyncio

from pallas.product.llm.memory.store import apply_memory_lifecycle_overlay


def test_lifecycle_overlay_skips_frozen_and_scales_score(monkeypatch) -> None:
    overlays = {
        1: {"weight": 2.0, "frozen": False, "entity_tags": []},
        2: {"weight": 1.0, "frozen": True, "entity_tags": []},
    }
    monkeypatch.setattr(
        "pallas.product.llm.memory.store.memory_lifecycle_overlay",
        lambda entry_id: overlays[entry_id],
    )

    result = apply_memory_lifecycle_overlay([{"id": 1, "score": 40}, {"id": 2, "score": 90}])

    assert result == [{"id": 1, "score": 80}]


def test_time_decay_factor_halves_after_half_life() -> None:
    from pallas.product.llm.memory.retrieve import memory_time_decay_factor

    now = 1_000_000_000.0
    # 30 天前（= half_life），低 importance → 系数约 0.5
    factor = memory_time_decay_factor(
        now - 30 * 86400,
        half_life_days=30,
        min_importance=0.6,
        importance=0.3,
        now=now,
    )
    assert 0.4 <= factor <= 0.6

    # 高 importance 不衰减
    factor_high = memory_time_decay_factor(
        now - 300 * 86400,
        half_life_days=30,
        min_importance=0.6,
        importance=0.8,
        now=now,
    )
    assert factor_high == 1.0

    # half_life<=0 不衰减
    factor_zero = memory_time_decay_factor(
        now - 999 * 86400, half_life_days=0, min_importance=0.6, importance=0.1, now=now
    )
    assert factor_zero == 1.0


def test_lifecycle_overlay_applies_time_decay(monkeypatch) -> None:
    from types import SimpleNamespace

    monkeypatch.setattr(
        "pallas.product.llm.memory.store.get_llm_config",
        lambda: SimpleNamespace(
            llm_memory_decay_half_life_days=30.0,
            llm_memory_decay_min_importance=0.6,
        ),
    )
    now = 1_000_000_000.0
    monkeypatch.setattr("pallas.product.llm.memory.store.time", SimpleNamespace(time=lambda: now))
    monkeypatch.setattr(
        "pallas.product.llm.memory.store.memory_lifecycle_overlay",
        lambda entry_id: {"weight": 1.0, "frozen": False, "entity_tags": []},
    )

    result = apply_memory_lifecycle_overlay([
        {"id": 1, "score": 100, "created_at": now, "importance": 0.3},
        {"id": 2, "score": 100, "created_at": now - 90 * 86400, "importance": 0.3},
    ])

    scores = {item["id"]: item["score"] for item in result}
    # 90 天前（3 个半衰期）→ 100 * 0.125 = 12.5 → 12
    assert scores[2] <= scores[1]
    assert scores[2] <= 13


def test_touch_updates_updated_at_when_not_in_cooldown(monkeypatch) -> None:
    from types import SimpleNamespace

    from pallas.product.llm.memory import store

    committed: list[str] = []

    class FakeSession:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_a):
            return False

        async def get(self, _model, entry_id):  # noqa: ARG002
            return SimpleNamespace(updated_at=0)

        async def commit(self):
            committed.append("commit")

    monkeypatch.setattr(store, "get_session", lambda **_: FakeSession())
    cfg = SimpleNamespace(llm_memory_hit_boost_enabled=True, llm_memory_hit_boost_sec=3600)
    asyncio.run(store.touch_memory_hit_timestamps([1], cfg=cfg))
    assert "commit" in committed


def test_touch_skips_when_disabled(monkeypatch) -> None:
    from types import SimpleNamespace

    from pallas.product.llm.memory import store

    committed: list[str] = []

    class FakeSession:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_a):
            return False

        async def commit(self):
            committed.append("commit")

    monkeypatch.setattr(store, "get_session", lambda **_: FakeSession())
    cfg = SimpleNamespace(llm_memory_hit_boost_enabled=False, llm_memory_hit_boost_sec=3600)
    asyncio.run(store.touch_memory_hit_timestamps([1], cfg=cfg))
    assert committed == []
