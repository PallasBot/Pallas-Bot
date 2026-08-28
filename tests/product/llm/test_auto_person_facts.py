from pallas.product.llm.memory.auto_person_facts import (
    _parse_facts,
    _user_turns,
)
from pallas.product.llm.memory.person_facts import save_person_fact
from pallas.product.llm.session_models import LlmChatTurn


def test_user_turns_only_keeps_user_role_until_limit() -> None:
    turns = [
        LlmChatTurn(role=u["role"], content=u["content"], user_id=u["user_id"], created_at=0)
        for u in [
            {"role": "user", "content": "a", "user_id": 1},
            {"role": "user", "content": "b", "user_id": 1},
            {"role": "user", "content": "c", "user_id": 1},
            {"role": "user", "content": "d", "user_id": 1},
            {"role": "user", "content": "e", "user_id": 1},
            {"role": "user", "content": "f", "user_id": 1},
            {"role": "user", "content": "g", "user_id": 1},
            {"role": "user", "content": "h", "user_id": 1},
            {"role": "user", "content": "i", "user_id": 1},
        ]
    ]
    out = _user_turns(turns)
    assert out.count("\n") == 7
    assert "i" not in out


def test_user_turns_rejects_empty_text() -> None:
    turns = [LlmChatTurn(role="user", content="   ", user_id=1, created_at=0)]
    assert _user_turns(turns) == ""


def test_parse_facts_handles_fenced_and_plain_json() -> None:
    assert _parse_facts('```json\n{"facts": ["爱发表情包", "喜欢夜聊"]}\n```') == ["爱发表情包", "喜欢夜聊"]
    assert _parse_facts('{"facts": []}') == []
    assert _parse_facts("not json") == []


def test_parse_facts_strips_trailing_punct_and_trims_length() -> None:
    import json

    payload = json.dumps({"facts": ["爱发表情包。", "x" * 100]}, ensure_ascii=False)
    out = _parse_facts(payload)
    assert out[0] == "爱发表情包"
    assert len(out[1]) <= 64


def test_save_person_fact_then_list(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(
        "pallas.product.llm.memory.person_facts._store_path",
        lambda: tmp_path / "person_facts.json",
    )
    save_person_fact(bot_id=1, group_id=2, user_id=3, content="爱发表情包", source="conversation")
    from pallas.product.llm.memory.person_facts import list_person_facts

    assert [f.content for f in list_person_facts(bot_id=1, group_id=2, user_id=3)] == ["爱发表情包"]
