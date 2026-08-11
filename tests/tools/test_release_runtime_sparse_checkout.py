from __future__ import annotations

import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SPARSE_MANIFEST = REPO_ROOT / ".github" / "release-runtime-sparse-checkout"


def run_git(cwd: Path, *args: str) -> str:
    return subprocess.check_output(["git", *args], cwd=cwd, text=True).strip()


def test_release_runtime_sparse_checkout_materializes_only_deployment_files(tmp_path: Path) -> None:
    assert SPARSE_MANIFEST.is_file()

    source = tmp_path / "source"
    source.mkdir()
    run_git(source, "init", "-q")
    run_git(source, "config", "user.name", "Test")
    run_git(source, "config", "user.email", "test@example.com")

    included = (
        "pyproject.toml",
        "pallas/app.py",
        "packages/plugin.py",
        "resource/data.json",
        "config/pallas.example.toml",
        "deploy/default/README.md",
        "scripts/run_unified_bot.sh",
        "tools/apply_deploy_profile.py",
        "tools/migrate_env_to_pallas.py",
        "tools/scripts/backup_database.py",
    )
    excluded = (
        "AGENTS.md",
        "CONTRIBUTING.md",
        "tests/test_app.py",
        "docs/guide.md",
        ".github/workflows/ci.yml",
        ".agents/skills/example.md",
        "templates/plugin/file.py",
        "openspec/api.json",
        "tools/check_plugin_imports.py",
        "tools/scripts/sync_docs_to_web.py",
    )
    for relative in (*included, *excluded):
        path = source / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(relative, encoding="utf-8")
    run_git(source, "add", ".")
    run_git(source, "commit", "-qm", "fixture")

    checkout = tmp_path / "checkout"
    subprocess.run(["git", "clone", "-q", "--no-checkout", str(source), str(checkout)], check=True)
    run_git(checkout, "sparse-checkout", "init", "--no-cone")
    sparse_file = checkout / ".git" / "info" / "sparse-checkout"
    sparse_file.write_text(SPARSE_MANIFEST.read_text(encoding="utf-8"), encoding="utf-8")
    run_git(checkout, "checkout", "-q", "HEAD")

    assert all((checkout / relative).is_file() for relative in included)
    assert all(not (checkout / relative).exists() for relative in excluded)
    assert run_git(checkout, "status", "--porcelain") == ""
