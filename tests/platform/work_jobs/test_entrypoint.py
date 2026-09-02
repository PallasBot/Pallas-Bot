from __future__ import annotations


def test_work_entrypoint_initializes_nonebot_before_loading_handlers(monkeypatch) -> None:
    import bot_work_aux

    calls: list[str] = []
    monkeypatch.setattr(bot_work_aux.nonebot, "init", lambda: calls.append("init"))
    monkeypatch.setattr(bot_work_aux, "repeater_work_handlers", lambda: calls.append("handlers") or {})
    monkeypatch.setattr(bot_work_aux, "load_external_work_handlers", dict)

    assert bot_work_aux.load_work_handlers() == {}
    assert calls == ["init", "handlers"]
