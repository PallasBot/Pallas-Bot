from __future__ import annotations

from pallas.product.arknights_kb.readiness import kb_data_ready, kb_status_snapshot, kb_sync_gaps


def test_kb_sync_gaps_when_only_operators_present(monkeypatch) -> None:
    monkeypatch.setattr(
        "pallas.product.arknights_kb.readiness.load_kb_operators_payload",
        lambda: {"count": 2, "operators": [{}, {}]},
    )
    monkeypatch.setattr("pallas.product.arknights_kb.readiness.load_enemies_payload", lambda: None)
    assert kb_sync_gaps() == ["handbook", "enemies"]
    assert kb_data_ready() is False


def test_kb_data_ready_when_all_present(monkeypatch) -> None:
    monkeypatch.setattr(
        "pallas.product.arknights_kb.readiness.load_kb_operators_payload",
        lambda: {
            "count": 400,
            "operators": [{"handbook_lines": ["基础档案：测试"]}],
            "handbook_enriched": True,
            "handbook_profiles": 1,
            "rarity_filter": "ALL",
            "source": "test",
        },
    )
    monkeypatch.setattr(
        "pallas.product.arknights_kb.readiness.load_enemies_payload",
        lambda: {"count": 1, "enemies": [{}]},
    )
    assert kb_sync_gaps() == []
    snapshot = kb_status_snapshot()
    assert snapshot["ready"] is True
    assert snapshot["operators_count"] == 400
    assert snapshot["handbook_profiles"] == 1
    assert snapshot["enemies_count"] == 1
