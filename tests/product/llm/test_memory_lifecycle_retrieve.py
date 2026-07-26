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
