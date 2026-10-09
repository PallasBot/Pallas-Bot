#!/usr/bin/env python3
"""Run pip-audit and fail on vulnerabilities or incomplete audit coverage."""

from __future__ import annotations

import json
import subprocess
import sys
import tomllib
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_EXCEPTIONS = PROJECT_ROOT / "config" / "dependency-audit-exceptions.toml"
_ROOT_EDITABLE_REASON = "distribution marked as editable"


class AuditConfigurationError(ValueError):
    pass


def load_exceptions(path: Path = DEFAULT_EXCEPTIONS, *, today: date | None = None) -> list[str]:
    try:
        config = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise AuditConfigurationError(f"Cannot read exception config {path}: {exc}") from exc

    entries = config.get("vulnerability", [])
    if not isinstance(entries, list):
        raise AuditConfigurationError("'vulnerability' must be an array of tables")
    current_date = today or datetime.now(UTC).date()
    ignored: list[str] = []
    for entry in entries:
        if not isinstance(entry, dict):
            raise AuditConfigurationError("Each vulnerability exception must be a table")
        vulnerability_id = entry.get("id")
        reason = entry.get("reason")
        expiry = entry.get("expires")
        if not isinstance(vulnerability_id, str) or not vulnerability_id.strip():
            raise AuditConfigurationError("Each vulnerability exception requires a non-empty id")
        if not isinstance(reason, str) or not reason.strip():
            raise AuditConfigurationError(f"Exception {vulnerability_id} requires a reason")
        if not isinstance(expiry, str):
            raise AuditConfigurationError(f"Exception {vulnerability_id} requires expires as YYYY-MM-DD")
        try:
            expires = date.fromisoformat(expiry)
        except ValueError as exc:
            raise AuditConfigurationError(f"Exception {vulnerability_id} has an invalid expiry date") from exc
        if expires.isoformat() != expiry:
            raise AuditConfigurationError(f"Exception {vulnerability_id} expiry must use YYYY-MM-DD")
        if current_date >= expires:
            raise AuditConfigurationError(f"Exception {vulnerability_id} expired on {expiry}")
        if vulnerability_id in ignored:
            raise AuditConfigurationError(f"Duplicate vulnerability exception {vulnerability_id}")
        ignored.append(vulnerability_id)
    return ignored


def validate_report(output: str) -> list[str]:
    try:
        report: Any = json.loads(output)
    except json.JSONDecodeError as exc:
        raise ValueError(f"pip-audit returned invalid JSON: {exc}") from exc
    if not isinstance(report, dict) or not isinstance(report.get("dependencies"), list):
        raise ValueError("pip-audit JSON is missing the dependencies list")
    if not report["dependencies"]:
        raise ValueError("pip-audit reported no dependencies; audit coverage is empty")

    vulnerabilities: list[str] = []
    skipped: list[str] = []
    resolved_count = 0
    for dependency in report["dependencies"]:
        if not isinstance(dependency, dict) or not isinstance(dependency.get("name"), str):
            raise ValueError("pip-audit JSON contains an invalid dependency entry")
        skip_reason = dependency.get("skip_reason")
        name = dependency["name"]
        if skip_reason is not None:
            if name.casefold() != "pallas-bot" or skip_reason != _ROOT_EDITABLE_REASON:
                skipped.append(f"{name}: {skip_reason}")
                continue
        vulns = dependency.get("vulns")
        if name.casefold() == "pallas-bot" and skip_reason == _ROOT_EDITABLE_REASON:
            continue
        version = dependency.get("version")
        if not name.strip() or not isinstance(version, str) or not version.strip() or not isinstance(vulns, list):
            raise ValueError(f"pip-audit JSON has invalid resolved dependency data for {name!r}")
        resolved_count += 1
        for vulnerability in vulns:
            if not isinstance(vulnerability, dict) or not isinstance(vulnerability.get("id"), str):
                raise ValueError(f"pip-audit JSON contains an invalid vulnerability for {name}")
            vulnerabilities.append(f"{name}: {vulnerability['id']}")
    if skipped:
        raise ValueError("Dependencies were skipped and could not be audited: " + ", ".join(skipped))
    if resolved_count == 0:
        raise ValueError("pip-audit resolved no dependencies; audit coverage is empty")
    return vulnerabilities


def run_audit(
    exceptions_path: Path = DEFAULT_EXCEPTIONS,
    *,
    today: date | None = None,
) -> int:
    try:
        ignored = load_exceptions(exceptions_path, today=today)
    except AuditConfigurationError as exc:
        print(f"Dependency audit configuration error: {exc}", file=sys.stderr)
        return 2

    command = [
        sys.executable,
        "-m",
        "pip_audit",
        "--local",
        "--skip-editable",
        "--progress-spinner",
        "off",
        "--format",
        "json",
    ]
    for vulnerability_id in ignored:
        command.extend(("--ignore-vuln", vulnerability_id))
    try:
        # Fixed argv; only validated TOML vulnerability IDs are dynamic argument values.
        # nosemgrep: python.lang.security.audit.dangerous-subprocess-use-audit
        result = subprocess.run(command, capture_output=True, text=True, check=False, shell=False)
    except OSError as exc:
        print(f"Could not run pip-audit: {exc}", file=sys.stderr)
        return 2

    try:
        vulnerabilities = validate_report(result.stdout)
    except ValueError as exc:
        print(f"Dependency audit report error: {exc}", file=sys.stderr)
        if result.stderr:
            print(result.stderr, file=sys.stderr, end="" if result.stderr.endswith("\n") else "\n")
        return 2
    if vulnerabilities:
        print("Dependency vulnerabilities found: " + ", ".join(vulnerabilities), file=sys.stderr)
    if result.returncode != 0:
        print(f"pip-audit exited with status {result.returncode}", file=sys.stderr)
        if result.stderr:
            print(result.stderr, file=sys.stderr, end="" if result.stderr.endswith("\n") else "\n")
        return result.returncode or 1
    if vulnerabilities:
        return 1
    print("Dependency audit passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(run_audit())
