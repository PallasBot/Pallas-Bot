from __future__ import annotations

from pallas.console.cli.log_paths import (
    EMBED_AUX_LOG,
    UNIFIED_BOT_LOG,
    list_default_log_targets,
    read_log_tail,
)


def test_list_default_log_targets_unified() -> None:
    targets = list_default_log_targets(mode="unified")
    labels = [label for label, _ in targets]
    assert labels[0] == "Bot (unified)"
    assert targets[0][1] == UNIFIED_BOT_LOG
    assert ("embed 辅进程", EMBED_AUX_LOG) in targets


def test_read_log_tail(tmp_path) -> None:
    path = tmp_path / "bot.log"
    path.write_text("a\nb\nc\nd\n", encoding="utf-8")
    assert read_log_tail(path, lines=2) == "c\nd"
    assert read_log_tail(tmp_path / "missing.log", lines=5) == ""
