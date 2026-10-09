from __future__ import annotations

import json
import subprocess
from datetime import date
from typing import TYPE_CHECKING

import pytest

from tools import audit_dependencies

if TYPE_CHECKING:
    from pathlib import Path


def report(*dependencies: dict[str, object]) -> str:
    return json.dumps({"dependencies": list(dependencies)})


def dependency(
    name: str = "example",
    *,
    vulns: list[dict[str, str]] | None = None,
    skip_reason: str | None = None,
) -> dict[str, object]:
    return {"name": name, "version": "1.0", "vulns": vulns or [], "skip_reason": skip_reason}


def mock_result(
    monkeypatch: pytest.MonkeyPatch, stdout: str, returncode: int = 0, stderr: str = ""
) -> list[tuple[list[str], dict[str, object]]]:
    calls: list[tuple[list[str], dict[str, object]]] = []

    def run(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        calls.append((command, kwargs))
        return subprocess.CompletedProcess(command, returncode, stdout, stderr)

    monkeypatch.setattr(audit_dependencies.subprocess, "run", run)
    return calls


def test_audit_accepts_clean_report_and_root_editable(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    config = tmp_path / "exceptions.toml"
    config.write_text("", encoding="utf-8")
    audited = dependency()
    del audited["skip_reason"]
    root = dependency("pallas-bot", skip_reason="distribution marked as editable")
    root["vulns"] = None
    mock_result(monkeypatch, report(audited, root))

    assert audit_dependencies.run_audit(config, today=date(2026, 10, 7)) == 0


def test_audit_rejects_report_with_only_root_editable(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    config = tmp_path / "exceptions.toml"
    config.write_text("", encoding="utf-8")
    root = {"name": "pallas-bot", "skip_reason": "distribution marked as editable"}
    mock_result(monkeypatch, report(root))

    assert audit_dependencies.run_audit(config, today=date(2026, 10, 7)) != 0


@pytest.mark.parametrize(
    "resolved",
    [
        {"name": "example", "vulns": []},
        {"name": "example", "version": 1, "vulns": []},
    ],
)
def test_audit_rejects_invalid_resolved_dependency(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    resolved: dict[str, object],
) -> None:
    config = tmp_path / "exceptions.toml"
    config.write_text("", encoding="utf-8")
    mock_result(monkeypatch, report(resolved))

    assert audit_dependencies.run_audit(config, today=date(2026, 10, 7)) != 0


@pytest.mark.parametrize(
    ("stdout", "returncode", "stderr"),
    [
        (report(dependency(vulns=[{"id": "CVE-2026-1234"}])), 1, ""),
        (report(dependency(vulns=[{"id": "CVE-2026-1234"}])), 0, ""),
        ("not json", 0, ""),
        (report(dependency("unknown", skip_reason="could not audit")), 0, ""),
        (report(dependency()), 2, "pip-audit failed"),
    ],
)
def test_audit_rejects_vulnerabilities_errors_and_incomplete_coverage(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    stdout: str,
    returncode: int,
    stderr: str,
) -> None:
    config = tmp_path / "exceptions.toml"
    config.write_text("", encoding="utf-8")
    mock_result(monkeypatch, stdout, returncode, stderr)

    assert audit_dependencies.run_audit(config, today=date(2026, 10, 7)) != 0


def test_audit_passes_exception_id_to_pip_audit(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    config = tmp_path / "exceptions.toml"
    config.write_text(
        '[[vulnerability]]\nid = "CVE-2026-1234"\nreason = "upstream fix pending"\nexpires = "2999-01-01"\n',
        encoding="utf-8",
    )
    # pip-audit applies --ignore-vuln before formatting; ignored findings are absent from JSON.
    calls = mock_result(monkeypatch, report(dependency()))

    assert audit_dependencies.run_audit(config, today=date(2026, 10, 7)) == 0
    command, options = calls[0]
    assert command == [
        audit_dependencies.sys.executable,
        "-m",
        "pip_audit",
        "--local",
        "--skip-editable",
        "--progress-spinner",
        "off",
        "--format",
        "json",
        "--ignore-vuln",
        "CVE-2026-1234",
    ]
    assert options["shell"] is False


@pytest.mark.parametrize(
    "content",
    [
        '[[vulnerability]]\nid = "CVE-2026-1234"\nreason = ""\nexpires = "2999-01-01"\n',
        '[[vulnerability]]\nid = "CVE-2026-1234"\nreason = "valid reason"\nexpires = "2020-01-01"\n',
        '[[vulnerability]]\nid = "CVE-2026-1234"\nreason = "valid reason"\nexpires = "2026-10-07"\n',
        '[[vulnerability]]\nid = "CVE-2026-1234"\nreason = "valid reason"\nexpires = "not-a-date"\n',
    ],
)
def test_audit_rejects_invalid_or_expired_exceptions(content: str, tmp_path: Path) -> None:
    config = tmp_path / "exceptions.toml"
    config.write_text(content, encoding="utf-8")

    with pytest.raises(audit_dependencies.AuditConfigurationError):
        audit_dependencies.load_exceptions(config, today=date(2026, 10, 7))
