from __future__ import annotations

from pallas.console.cli.log_color import colorize_line, colorize_source


def test_color_disabled_when_not_tty(monkeypatch) -> None:
    class FakeStdout:
        def isatty(self) -> bool:
            return False

    monkeypatch.setattr("pallas.console.cli.log_color.sys.stdout", FakeStdout())
    line = "08-18 13:33:57 [SUCCESS ] {Message } Bot replied"
    assert colorize_line(line) == line
    assert colorize_source("Bot 业务日志") == "Bot 业务日志"


def test_colorize_line_level_and_time(monkeypatch) -> None:
    class FakeStdout:
        def isatty(self) -> bool:
            return True

    monkeypatch.setattr("pallas.console.cli.log_color.sys.stdout", FakeStdout())
    line = "08-18 13:33:57 [SUCCESS ] {Message } Bot replied"
    colored = colorize_line(line)
    assert "\x1b[32m08-18 13:33:57\x1b[0m" in colored
    assert "\x1b[32m[SUCCESS ]\x1b[0m" in colored
    assert "Bot replied" in colored


def test_colorize_line_unknown_level_stays_plain(monkeypatch) -> None:
    class FakeStdout:
        def isatty(self) -> bool:
            return True

    monkeypatch.setattr("pallas.console.cli.log_color.sys.stdout", FakeStdout())
    line = "08-18 13:33:57 [NOTALEVEL] hello"
    colored = colorize_line(line)
    assert "[NOTALEVEL]" in colored
    assert colored.count("\x1b[") == 2  # 仅时间被染色，级别不染色
    assert colored.endswith(" hello")


def test_colorize_source_stable_per_label(monkeypatch) -> None:
    class FakeStdout:
        def isatty(self) -> bool:
            return True

    monkeypatch.setattr("pallas.console.cli.log_color.sys.stdout", FakeStdout())
    assert colorize_source("hub") == colorize_source("hub")
    colored = colorize_source("hub")
    assert colored.startswith("\x1b[")
    assert colored.endswith("\x1b[0m")
