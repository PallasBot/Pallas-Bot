from __future__ import annotations

from types import SimpleNamespace


def make_entry(store, *, support: int = 3, source: str = "llm_success", status: str = "shadow"):
    return store.ExpressionEntry(
        entry_id="expression-1",
        group_id=10001,
        occasion="吐槽",
        saying="这也太离谱了吧",
        support=support,
        source=source,
        channel="at_chat",
        scene_tier="strong",
        status=status,
        affect_hint="complain",
        created_at=1,
        updated_at=1,
    )


def test_expression_auto_eligibility_requires_shadow_llm_success_and_support() -> None:
    from pallas.product.persona import expression_bank as store
    from pallas.product.persona.expression_promote import is_expression_auto_eligible

    assert is_expression_auto_eligible(make_entry(store))
    assert not is_expression_auto_eligible(make_entry(store, support=2))
    assert not is_expression_auto_eligible(make_entry(store, source="group_observe"))
    assert not is_expression_auto_eligible(make_entry(store, status="active"))


def test_resolve_expression_approves_or_rejects_persisted_entry(monkeypatch, tmp_path) -> None:
    from pallas.product.persona import expression_bank as store
    from pallas.product.persona.expression_promote import resolve_expression

    monkeypatch.setenv("PALLAS_DATA_DIR", str(tmp_path))
    saved = store.append_or_merge_expression(make_entry(store))

    approved = resolve_expression(saved.entry_id, action="approve")
    assert approved is not None
    assert approved.status == "active"
    assert approved.rejected_reason == ""

    rejected = resolve_expression(saved.entry_id, action="reject", reason="不符合群聊习惯")
    assert rejected is not None
    assert rejected.status == "rejected"
    assert rejected.rejected_reason == "不符合群聊习惯"


def test_maybe_auto_promote_activates_eligible_group_entries(monkeypatch, tmp_path) -> None:
    from pallas.product.persona import expression_bank as store
    from pallas.product.persona import expression_promote as promote

    monkeypatch.setenv("PALLAS_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(
        promote,
        "get_llm_config",
        lambda: SimpleNamespace(llm_expression_auto_promote_enabled=True),
    )
    saved = store.append_or_merge_expression(make_entry(store))

    promoted = promote.maybe_auto_promote_for_group(10001)

    assert [entry.entry_id for entry in promoted] == [saved.entry_id]
    assert store.list_group_expressions(10001)[0].status == "active"
