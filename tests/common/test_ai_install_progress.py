"""AI Runtime 安装 job 进度与 bootstrap 流式输出。"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from pallas.console.cli import ai_install
from pallas.console.webui import ai_install_progress as progress

if TYPE_CHECKING:
    from pathlib import Path


@pytest.mark.asyncio
async def test_ai_install_job_progress_and_complete() -> None:
    job = progress.create_ai_install_job("bootstrap")
    assert progress.get_ai_install_job(job.job_id) is job
    assert job.phase == "queued"
    assert job.progress_percent == 0

    def runner(j: progress.AiInstallJob) -> None:
        j.push("running", "bootstrap…", progress_percent=45, line="step-1")
        j.result = {"exit_code": 0}
        j.message = "bootstrap 完成"

    await progress.run_ai_install_job(job, runner)
    assert job.phase == "done"
    assert job.progress_percent == 100
    assert job.log_lines == ["step-1"]
    assert any(ev.get("progress_percent") == 45 for ev in job.events)


@pytest.mark.asyncio
async def test_ai_install_job_failed_keeps_percent() -> None:
    job = progress.create_ai_install_job("clone")

    def runner(j: progress.AiInstallJob) -> None:
        j.push("failed", error="boom", progress_percent=33)

    await progress.run_ai_install_job(job, runner)
    assert job.phase == "failed"
    assert job.error == "boom"
    assert job.progress_percent == 33


@pytest.mark.asyncio
async def test_ai_install_sse_includes_percent_and_lines() -> None:
    job = progress.create_ai_install_job("clone_and_bootstrap")
    job.push("running", "clone", progress_percent=10)
    job.push("running", "pip…", progress_percent=50, line="Collecting torch")
    job.push("done", "完成", progress_percent=100, result={"ok": True})

    chunks = [chunk async for chunk in progress.iter_ai_install_job_sse(job.job_id)]
    body = "".join(chunks)
    assert '"progress_percent": 10' in body or '"progress_percent":10' in body
    assert "Collecting torch" in body
    assert '"type": "complete"' in body or '"type":"complete"' in body


def test_bootstrap_line_progress_caps() -> None:
    assert progress.bootstrap_line_progress(0) == progress.PCT_BOOTSTRAP
    assert progress.bootstrap_line_progress(1000) == progress.PCT_BOOTSTRAP_CAP


def test_run_ai_bootstrap_streams_lines(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    script = tmp_path / "scripts" / "ai_bootstrap.sh"
    script.parent.mkdir(parents=True)
    script.write_text("#!/bin/sh\n", encoding="utf-8")

    class FakeStdout:
        def __init__(self) -> None:
            self._lines = iter(["line-a\n", "line-b\n"])

        def __iter__(self):
            return self._lines

    class FakeProc:
        stdout = FakeStdout()

        def wait(self) -> int:
            return 0

        def kill(self) -> None:
            return None

    monkeypatch.setattr(
        "pallas.console.cli.process_util.bash_script_cmd",
        lambda script, *a, **k: ["/bin/bash", str(script), *a],
    )
    captured_kwargs: dict[str, object] = {}
    captured_cmd: list[str] = []

    def fake_popen(cmd, **k):
        captured_cmd.extend(cmd)
        captured_kwargs.update(k)
        return FakeProc()

    monkeypatch.setattr(
        ai_install.subprocess,
        "Popen",
        fake_popen,
    )
    monkeypatch.setattr(
        "pallas.console.cli.ai_supervisor.is_managed_ai_root",
        lambda _p: False,
    )

    seen: list[str] = []
    code, out = ai_install.run_ai_bootstrap_captured(
        ai_root=tmp_path,
        on_output_line=seen.append,
    )
    assert code == 0
    assert seen == ["line-a", "line-b"]
    assert "line-a" in out
    assert "AI 仓:" in out
    assert captured_kwargs.get("encoding") == "utf-8"
    assert captured_kwargs.get("errors") == "replace"
    env = captured_kwargs.get("env")
    assert isinstance(env, dict)
    assert env.get("PYTHONUTF8") == "1"
    assert env.get("PYTHONIOENCODING") == "utf-8"


def test_run_ai_bootstrap_missing_script(tmp_path: Path) -> None:
    code, out = ai_install.run_ai_bootstrap_captured(ai_root=tmp_path)
    assert code == 1
    assert "未找到" in out
