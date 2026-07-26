from pallas.product.llm.memory.consent import (
    can_use_global_person_facts,
    get_consent,
    set_consent,
)
from pallas.product.llm.memory.person_facts import (
    freeze_person_fact,
    list_person_facts,
    retrieve_person_facts_for_prompt,
    save_person_fact,
)


def test_person_facts_are_group_scoped_until_consent(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(
        "pallas.product.llm.memory.person_facts._store_path",
        lambda: tmp_path / "person_facts.json",
    )
    monkeypatch.setattr(
        "pallas.product.llm.memory.consent._store_path",
        lambda: tmp_path / "person_consent.json",
    )

    fact = save_person_fact(
        bot_id=1,
        group_id=2,
        user_id=3,
        content="喜欢猫",
        source="conversation",
        confidence=0.9,
    )
    assert fact.scope == "group"
    assert len(list_person_facts(bot_id=1, group_id=2, user_id=3)) == 1
    assert not can_use_global_person_facts(3, platform="qq")
    assert get_consent(3, platform="qq").granted is False

    set_consent(3, platform="qq", granted=True, scopes=["stable_preferences"])
    assert can_use_global_person_facts(3, platform="qq")
    frozen = freeze_person_fact(fact.fact_id)
    assert frozen is not None
    assert retrieve_person_facts_for_prompt(bot_id=1, group_id=2, user_id=3) == []
