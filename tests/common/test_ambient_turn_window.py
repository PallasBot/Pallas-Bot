from __future__ import annotations

from pallas.product.llm import ambient_turn_window as mod


def test_ambient_turn_coalesces_within_idle(monkeypatch) -> None:
    mod.clear_ambient_turn_buffers_for_tests()
    monkeypatch.setattr(mod, "ambient_turn_window_enabled", lambda: True)
    monkeypatch.setattr(mod, "ambient_turn_idle_sec", lambda: 10.0)

    ok, text = mod.note_ambient_turn_and_should_flush(
        bot_id=1,
        group_id=2,
        user_id=3,
        text="第一条",
        force=False,
    )
    assert ok is True
    assert text == "第一条"

    ok2, _ = mod.note_ambient_turn_and_should_flush(
        bot_id=1,
        group_id=2,
        user_id=3,
        text="第二条",
        force=False,
    )
    assert ok2 is False


def test_ambient_turn_force_bypasses_window(monkeypatch) -> None:
    mod.clear_ambient_turn_buffers_for_tests()
    monkeypatch.setattr(mod, "ambient_turn_window_enabled", lambda: True)
    monkeypatch.setattr(mod, "ambient_turn_idle_sec", lambda: 10.0)
    mod.note_ambient_turn_and_should_flush(bot_id=1, group_id=2, user_id=3, text="a", force=False)
    ok, text = mod.note_ambient_turn_and_should_flush(
        bot_id=1,
        group_id=2,
        user_id=3,
        text="点名",
        force=True,
    )
    assert ok is True
    assert text == "点名"
