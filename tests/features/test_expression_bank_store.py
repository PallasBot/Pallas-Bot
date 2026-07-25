from __future__ import annotations

import importlib
import importlib.util


def expression_bank():
    module_name = "pallas.product.persona.expression_bank"
    assert importlib.util.find_spec(module_name) is not None
    return importlib.import_module(module_name)


def test_expression_entry_smoke_and_key_normalization() -> None:
    store = expression_bank()

    entry = store.ExpressionEntry(
        entry_id="entry-1",
        group_id=10001,
        occasion="  朋友吐槽加班  ",
        saying="  我也想下班啊  ",
        source="group_observe",
        channel="group",
        scene_tier="casual",
        status="shadow",
        affect_hint="tired",
        created_at=1,
        updated_at=1,
    )

    assert entry.support == 1
    assert entry.bot_id == 0
    assert entry.rejected_reason == ""
    assert store.normalize_expression_key(" x" * 30, " y" * 30) == (
        "x x x x x x x x x x",
        "y y y y y y y y y y",
    )
    assert store.build_entry_id(entry.group_id, ("朋友吐槽加班", "我也想下班啊")) == store.build_entry_id(
        entry.group_id,
        ("朋友吐槽加班", "我也想下班啊"),
    )


def test_append_or_merge_increments_support_and_keeps_llm_source(monkeypatch, tmp_path) -> None:
    store = expression_bank()
    monkeypatch.setenv("PALLAS_DATA_DIR", str(tmp_path))

    observed = store.ExpressionEntry(
        entry_id="first",
        group_id=10001,
        occasion="吐槽加班",
        saying="我也想下班啊",
        source="group_observe",
        channel="group",
        scene_tier="casual",
        status="shadow",
        affect_hint="tired",
        created_at=10,
        updated_at=10,
    )
    successful = observed.model_copy(
        update={
            "entry_id": "second",
            "source": "llm_success",
            "support": 3,
            "updated_at": 20,
        }
    )

    assert store.append_or_merge_expression(observed).support == 1
    merged = store.append_or_merge_expression(successful)

    assert merged.support == 4
    assert merged.source == "llm_success"
    assert merged.entry_id == store.build_entry_id(10001, ("吐槽加班", "我也想下班啊"))
    assert len(store.list_group_expressions(10001)) == 1


def test_append_or_merge_does_not_revive_rejected_entry(monkeypatch, tmp_path) -> None:
    store = expression_bank()
    monkeypatch.setenv("PALLAS_DATA_DIR", str(tmp_path))

    rejected = store.ExpressionEntry(
        entry_id="rejected",
        group_id=10001,
        occasion="吐槽加班",
        saying="我也想下班啊",
        source="llm_success",
        channel="group",
        scene_tier="casual",
        status="rejected",
        affect_hint="tired",
        created_at=10,
        updated_at=10,
        rejected_reason="manual review",
    )
    incoming = rejected.model_copy(update={"entry_id": "new", "status": "active", "support": 2, "updated_at": 20})

    merged = store.append_or_merge_expression(rejected)
    unchanged = store.append_or_merge_expression(incoming)

    assert merged.status == "rejected"
    assert unchanged.status == "rejected"
    assert unchanged.support == 3
    assert unchanged.rejected_reason == "manual review"
