from __future__ import annotations


def test_work_entrypoint_initializes_nonebot_before_loading_handlers(monkeypatch) -> None:
    import bot_work

    calls: list[str] = []
    monkeypatch.setattr(bot_work.nonebot, "init", lambda: calls.append("init"))
    monkeypatch.setattr(bot_work, "repeater_work_handlers", lambda: calls.append("handlers") or {})

    assert bot_work.load_work_handlers() == {}
    assert calls == ["init", "handlers"]
