from __future__ import annotations

from pathlib import Path

from pallas.core.foundation.paths import is_pallas_bot_root, resolve_project_root


def test_is_pallas_bot_root_for_repo() -> None:
    root = Path(__file__).resolve().parents[2]
    assert is_pallas_bot_root(root)


def test_is_pallas_bot_root_rejects_empty_dir(tmp_path: Path) -> None:
    assert not is_pallas_bot_root(tmp_path)


def test_resolve_project_root_from_repo_file() -> None:
    root = resolve_project_root(prefer_cwd=False)
    assert is_pallas_bot_root(root)
    assert (root / "bot_hub.py").is_file()


def test_resolve_project_root_prefers_cwd(monkeypatch, tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[2]
    sub = repo_root / "data" / "test_project_root_cwd"
    sub.mkdir(parents=True, exist_ok=True)
    monkeypatch.chdir(sub)
    resolved = resolve_project_root(prefer_cwd=True)
    assert resolved == repo_root
