from __future__ import annotations

import importlib
import importlib.util
from types import SimpleNamespace


def expression_learn():
    module_name = "pallas.product.persona.expression_learn"
    assert importlib.util.find_spec(module_name) is not None
    return importlib.import_module(module_name)


def test_expression_learning_safety_rejects_protocol_commands_and_system_text() -> None:
    learn = expression_learn()

    assert learn.is_saying_safe_for_expression("那确实")
    assert not learn.is_saying_safe_for_expression("好")
    assert not learn.is_saying_safe_for_expression("x" * 21)
    assert not learn.is_saying_safe_for_expression("[CQ:face,id=14]")
    assert not learn.is_saying_safe_for_expression("/ban 123")
    assert not learn.is_saying_safe_for_expression("管理命令123")
    assert not learn.is_saying_safe_for_expression("欢迎新人进群")
    assert not learn.is_saying_safe_for_expression("谢谢您的陪伴")


def test_propose_expression_builds_clean_affect_aligned_draft() -> None:
    learn = expression_learn()

    entry = learn.propose_expression_from_utterance(
        "  这也太离谱了吧  ",
        source="group_observe",
        channel="group",
        scene_tier="casual",
    )

    assert entry is not None
    assert entry.group_id == 0
    assert entry.saying == "这也太离谱了吧"
    assert entry.occasion == "venting"
    assert entry.affect_hint == "complain"
    assert entry.source == "group_observe"
    assert entry.channel == "group"
    assert entry.scene_tier == "casual"
    assert entry.status == "shadow"
    assert len(entry.saying) <= 20


def test_note_expression_respects_config_and_merges_llm_success_weight(monkeypatch, tmp_path) -> None:
    learn = expression_learn()
    monkeypatch.setenv("PALLAS_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(learn, "get_llm_config", lambda: SimpleNamespace(llm_expression_learn_enabled=False))

    assert learn.note_expression_from_utterance(10001, "那确实", channel="group") is None

    monkeypatch.setattr(learn, "get_llm_config", lambda: SimpleNamespace(llm_expression_learn_enabled=True))
    saved = learn.note_expression_from_utterance(10001, "那确实", channel="group", scene_tier="casual")

    assert saved is not None
    assert saved.group_id == 10001
    assert saved.source == "llm_success"
    assert saved.support == 1
    assert saved.status == "shadow"
    assert learn.note_expression_from_utterance(10001, "[CQ:face,id=14]", channel="group") is None

    from pallas.product.persona.expression_bank import list_group_expressions

    entries = list_group_expressions(10001)
    assert len(entries) == 1
    assert entries[0].support == 1


def test_note_expression_llm_success_respects_cooldown(monkeypatch, tmp_path) -> None:
    learn = expression_learn()
    monkeypatch.setenv("PALLAS_DATA_DIR", str(tmp_path))
    learn.clear_expression_learn_cooldown_state()
    monkeypatch.setattr(
        learn,
        "get_llm_config",
        lambda: SimpleNamespace(llm_expression_learn_enabled=True, llm_expression_learn_cooldown_sec=300),
    )
    first = learn.note_expression_from_utterance(10001, "那确实", channel="group", source="llm_success")
    second = learn.note_expression_from_utterance(10001, "那确实", channel="group", source="llm_success")
    assert first is not None
    assert second is None
    learn.clear_expression_learn_cooldown_state()
    third = learn.note_expression_from_utterance(10001, "那确实", channel="group", source="llm_success")
    assert third is not None
    assert third.support >= 2  # merge increments support


def test_group_observe_learning_batches_safe_messages(monkeypatch, tmp_path) -> None:
    learn = expression_learn()
    monkeypatch.setenv("PALLAS_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(learn, "get_llm_config", lambda: SimpleNamespace(llm_expression_learn_enabled=True))

    saved = learn.learn_expressions_from_group_messages(
        10001,
        ["那确实", "[CQ:face,id=14]", "这也太离谱了吧", "好耶"],
        bot_id=20002,
        max_notes=2,
    )

    assert [entry.saying for entry in saved] == ["那确实", "这也太离谱了吧"]
    assert all(entry.source == "group_observe" for entry in saved)
    assert all(entry.channel == "group_observe" for entry in saved)
