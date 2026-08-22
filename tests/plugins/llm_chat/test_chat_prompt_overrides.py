from __future__ import annotations

from packages.llm_chat import chat_message


def test_load_chat_prompt_overrides_is_group_scoped(monkeypatch) -> None:
    expected = {"persona": {"mode": "replace", "content": "群专属人格"}}
    calls: list[tuple[int, int]] = []

    def fake_load(*, bot_id: int, group_id: int):
        calls.append((bot_id, group_id))
        return expected

    monkeypatch.setattr(chat_message, "load_prompt_overrides", fake_load)

    assert chat_message.load_chat_prompt_overrides(10001, 20002) == expected
    assert chat_message.load_chat_prompt_overrides(10001, None) is None
    assert calls == [(10001, 20002)]
