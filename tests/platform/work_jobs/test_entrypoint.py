from __future__ import annotations


def test_work_entrypoint_initializes_nonebot_before_loading_handlers(monkeypatch) -> None:
    import bot_work_aux

    calls: list[str] = []
    monkeypatch.setattr(bot_work_aux.nonebot, "init", lambda: calls.append("init"))
    monkeypatch.setattr(bot_work_aux, "repeater_work_handlers", lambda: calls.append("handlers") or {})
    monkeypatch.setattr(bot_work_aux, "load_external_work_handlers", dict)

    assert bot_work_aux.load_work_handlers() == {}
    assert calls == ["init", "handlers"]


def test_work_entrypoint_puts_interactive_jobs_before_repeater_backlog(monkeypatch) -> None:
    import bot_work_aux

    captured: dict = {}

    async def fake_run_work_service(handlers, *, exclude_kinds=None, priority_tiers=None) -> None:
        captured["priority_tiers"] = priority_tiers

    monkeypatch.setattr(bot_work_aux, "load_work_handlers", dict)
    monkeypatch.setattr(bot_work_aux, "apply_repo_settings_to_environ", lambda: None)
    monkeypatch.setattr(bot_work_aux, "install_uvloop", lambda: None)
    monkeypatch.setattr(bot_work_aux, "run_work_service", fake_run_work_service)

    bot_work_aux.main()

    tiers = captured["priority_tiers"]
    assert tiers is not None
    interactive_rank = next(index for index, tier in enumerate(tiers) if "sing.submit" in tier)
    message_rank = next(index for index, tier in enumerate(tiers) if "repeater.message" in tier)
    assert interactive_rank < message_rank
