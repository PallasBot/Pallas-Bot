"""Windows bash 解析：优先 Git Bash，WSL system32 bash 需转换盘符路径。"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import Mock

from pallas.console.cli import process_util


def test_is_wsl_system_bash() -> None:
    assert process_util.is_wsl_system_bash(Path(r"C:\Windows\System32\bash.exe"))
    assert process_util.is_wsl_system_bash(Path(r"C:\Windows\system32\bash.EXE"))
    assert not process_util.is_wsl_system_bash(Path(r"C:\Program Files\Git\bin\bash.exe"))


def test_windows_path_to_wsl() -> None:
    assert process_util.windows_path_to_wsl(Path(r"F:\Pallas-Bot\data\runtimes\x\scripts\ai_bootstrap.sh")) == (
        "/mnt/f/Pallas-Bot/data/runtimes/x/scripts/ai_bootstrap.sh"
    )


def test_path_for_bash_converts_only_for_wsl(monkeypatch) -> None:
    monkeypatch.setattr(process_util, "is_windows", lambda: True)
    script = Path(r"F:\Pallas-Bot\scripts\ai_bootstrap.sh")
    wsl = Path(r"C:\Windows\System32\bash.exe")
    git = Path(r"C:\Program Files\Git\bin\bash.exe")
    assert process_util.path_for_bash(script, wsl).startswith("/mnt/f/")
    assert process_util.path_for_bash(script, git) == str(script)


def test_resolve_bash_prefers_git_over_wsl(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(process_util, "is_windows", lambda: True)
    git = tmp_path / "Git" / "bin" / "bash.exe"
    git.parent.mkdir(parents=True)
    git.write_text("", encoding="utf-8")
    monkeypatch.setattr(
        process_util,
        "windows_git_bash_candidates",
        lambda: [git],
    )
    monkeypatch.setattr(
        process_util.shutil,
        "which",
        lambda _name: r"C:\Windows\System32\bash.exe",
    )
    assert process_util.resolve_bash() == git


def test_bash_script_cmd_uses_wsl_path(monkeypatch) -> None:
    monkeypatch.setattr(process_util, "is_windows", lambda: True)
    wsl = Path(r"C:\Windows\System32\bash.exe")
    monkeypatch.setattr(process_util, "resolve_bash", lambda: wsl)
    script = Path(r"F:\Pallas-Bot\data\runtimes\pallas-bot-ai\scripts\ai_bootstrap.sh")
    cmd = process_util.bash_script_cmd(script, "--bot-port", "8088")
    assert cmd == [
        str(wsl),
        "/mnt/f/Pallas-Bot/data/runtimes/pallas-bot-ai/scripts/ai_bootstrap.sh",
        "--bot-port",
        "8088",
    ]


def test_bash_missing_message_mentions_git_and_system32() -> None:
    msg = process_util.bash_missing_message(purpose="AI Runtime bootstrap")
    assert "AI Runtime bootstrap" in msg
    if process_util.is_windows():
        assert "Git" in msg
        assert "System32" in msg


def test_windows_stop_pid_discards_taskkill_output(monkeypatch) -> None:
    run = Mock()
    monkeypatch.setattr(process_util.subprocess, "run", run)

    process_util._windows_stop_pid(123, force=True, timeout_s=1.0)

    kwargs = run.call_args.kwargs
    assert kwargs["stdout"] is process_util.subprocess.DEVNULL
    assert kwargs["stderr"] is process_util.subprocess.DEVNULL
    assert "text" not in kwargs
