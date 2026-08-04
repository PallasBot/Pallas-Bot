from __future__ import annotations

from pallas.console.cli.log_paths import EMBED_AUX_LOG, list_default_log_targets, read_log_tail


def test_list_default_log_targets_unified(monkeypatch, tmp_path) -> None:
    from pallas.console.cli import log_paths

    monkeypatch.setattr(log_paths, "BOT_LOG_DIR", tmp_path)
    bot_log = tmp_path / "nonebot_2026-08-04_18-00-00.log"
    bot_log.write_text("business log", encoding="utf-8")

    targets = list_default_log_targets(mode="unified")
    assert targets[0] == ("Bot 业务日志", bot_log)
    assert ("embed 辅进程", EMBED_AUX_LOG) in targets


def test_read_log_tail(tmp_path) -> None:
    path = tmp_path / "bot.log"
    path.write_text("a\nb\nc\nd\n", encoding="utf-8")
    assert read_log_tail(path, lines=2) == "c\nd"
    assert read_log_tail(tmp_path / "missing.log", lines=5) == ""
