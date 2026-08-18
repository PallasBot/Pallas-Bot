from __future__ import annotations

from typing import TYPE_CHECKING

from pallas.console.cli.log_paths import (
    EMBED_AUX_LOG,
    list_default_log_targets,
    read_log_tail,
    stream_log_targets,
)

if TYPE_CHECKING:
    from pathlib import Path


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


def test_latest_unified_launcher_log(monkeypatch, tmp_path) -> None:
    import os

    from pallas.console.cli import log_paths

    log_dir = tmp_path / "logs"
    log_dir.mkdir()
    old = log_dir / "bot_2026-08-01_00-00-00.log"
    old.write_text("old", encoding="utf-8")
    newest = log_dir / "bot_2026-08-02_00-00-00.log"
    newest.write_text("new", encoding="utf-8")
    os.utime(old, (1_700_000_000, 1_700_000_000))
    os.utime(newest, (1_700_000_001, 1_700_000_001))
    monkeypatch.setattr(log_paths, "UNIFIED_LAUNCHER_LOG_DIR", log_dir)
    assert log_paths.latest_unified_launcher_log() == newest
    monkeypatch.setattr(log_paths, "UNIFIED_LAUNCHER_LOG_DIR", tmp_path / "missing")
    assert log_paths.latest_unified_launcher_log() is None


def test_resolve_follow_targets_resolves_launcher_dir(monkeypatch, tmp_path) -> None:
    from pallas.console.cli import log_paths

    monkeypatch.setattr(log_paths, "BOT_LOG_DIR", tmp_path)
    log_dir = tmp_path / "logs"
    log_dir.mkdir()
    launcher = log_dir / "bot_2026-08-02_00-00-00.log"
    launcher.write_text("x", encoding="utf-8")
    monkeypatch.setattr(log_paths, "UNIFIED_LAUNCHER_LOG_DIR", log_dir)

    targets = log_paths.resolve_follow_targets(mode="unified")
    resolved = dict(targets)
    assert "启动器日志" in resolved
    assert resolved["启动器日志"]() == launcher


def test_stream_log_targets_tail_then_follow(tmp_path) -> None:
    path = tmp_path / "bot.log"
    path.write_text("a1\na2\n", encoding="utf-8")
    gen = stream_log_targets([("Bot", path)], lines=1, poll=0.01)
    assert next(gen) == ("Bot", "a2")
    with path.open("a", encoding="utf-8") as fh:
        fh.write("a3\n")
    assert next(gen) == ("Bot", "a3")


def test_stream_log_targets_partial_line(tmp_path) -> None:
    path = tmp_path / "bot.log"
    path.write_text("seed\n", encoding="utf-8")
    gen = stream_log_targets([("Bot", path)], lines=1, poll=0.01)
    assert next(gen) == ("Bot", "seed")
    with path.open("a", encoding="utf-8") as fh:
        fh.write("partial")
    with path.open("a", encoding="utf-8") as fh:
        fh.write(" line\n")
    assert next(gen) == ("Bot", "partial line")


def test_stream_log_targets_rotation(tmp_path) -> None:
    path = tmp_path / "bot.log"
    path.write_text("a1\na2\na3\na4\n", encoding="utf-8")
    gen = stream_log_targets([("Bot", path)], lines=1, poll=0.01)
    assert next(gen) == ("Bot", "a4")
    path.write_text("new1\nnew2\n", encoding="utf-8")
    assert next(gen) == ("Bot", "== bot.log 已轮转，重新跟随 ==")
    assert next(gen) == ("Bot", "new1")
    assert next(gen) == ("Bot", "new2")


def test_stream_log_targets_switch_dynamic(tmp_path) -> None:
    first = tmp_path / "bot_1.log"
    second = tmp_path / "bot_2.log"
    first.write_text("a1\n", encoding="utf-8")
    second.write_text("b1\nb2\n", encoding="utf-8")
    current = first

    def resolver() -> Path:
        return current

    gen = stream_log_targets([("启动器日志", resolver)], lines=1, poll=0.01)
    assert next(gen) == ("启动器日志", "a1")
    with first.open("a", encoding="utf-8") as fh:
        fh.write("a2\n")
    assert next(gen) == ("启动器日志", "a2")
    current = second
    assert next(gen) == ("启动器日志", "== 日志切换，跟随 bot_2.log ==")
    assert next(gen) == ("启动器日志", "b2")


def test_stream_log_targets_skips_missing_then_picks_up(tmp_path) -> None:
    seed = tmp_path / "seed.log"
    seed.write_text("s1\n", encoding="utf-8")
    path = tmp_path / "bot.log"
    gen = stream_log_targets([("Seed", seed), ("Bot", path)], lines=1, poll=0.01)
    assert next(gen) == ("Seed", "s1")
    path.write_text("late\n", encoding="utf-8")
    assert next(gen) == ("Bot", "late")
