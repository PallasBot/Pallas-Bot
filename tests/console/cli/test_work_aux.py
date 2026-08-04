from __future__ import annotations

from unittest.mock import Mock


def test_work_aux_starts_detached_service_when_database_is_supported(monkeypatch, tmp_path):
    from pallas.console.cli import work_aux

    monkeypatch.setattr(work_aux, "RUN_DIR", tmp_path / "run")
    monkeypatch.setattr(work_aux, "LOG_DIR", tmp_path / "logs")
    monkeypatch.setattr(work_aux, "PID_FILE", tmp_path / "run" / "work.pid")
    monkeypatch.setattr(work_aux, "LOG_FILE", tmp_path / "logs" / "work.log")
    monkeypatch.setattr(work_aux, "work_aux_should_run", lambda: True)
    monkeypatch.setattr(work_aux, "work_aux_running", lambda: False)
    spawn = Mock(return_value=321)
    monkeypatch.setattr(work_aux, "spawn_detached", spawn)

    assert work_aux.start_work_aux() == 0

    assert work_aux.PID_FILE.read_text(encoding="utf-8") == "321\n"
    assert spawn.call_args.args[0][-1] == "bot_work.py"


def test_work_aux_skips_when_database_backend_is_not_supported(monkeypatch):
    from pallas.console.cli import work_aux

    monkeypatch.setattr("pallas.core.foundation.config.repo_settings.apply_repo_settings_to_environ", lambda: None)
    monkeypatch.setattr("pallas.core.foundation.db.get_db_backend", lambda: "sqlite")

    assert work_aux.work_aux_should_run() is False


def test_unified_aux_start_includes_work_consumer(monkeypatch) -> None:
    from pallas.console.cli import unified_lifecycle

    calls: list[str] = []
    monkeypatch.setattr("pallas.console.cli.embedding_aux.start_embed_aux", lambda: calls.append("embed") or 0)
    monkeypatch.setattr("pallas.console.cli.work_aux.start_work_aux", lambda: calls.append("work") or 0)

    assert unified_lifecycle.start_aux_services() == 0
    assert calls == ["embed", "work"]
