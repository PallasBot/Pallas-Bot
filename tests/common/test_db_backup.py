from __future__ import annotations

import pytest

from pallas.core.foundation.db import backup as mod


def test_resolve_backup_parent_default(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(mod, "PROJECT_ROOT", tmp_path)
    parent = mod.resolve_backup_parent(None)
    assert parent == (tmp_path / "backups").resolve()
    assert parent.is_dir()


def test_resolve_backup_parent_relative(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(mod, "PROJECT_ROOT", tmp_path)
    parent = mod.resolve_backup_parent("custom/backups")
    assert parent == (tmp_path / "custom" / "backups").resolve()


def test_make_backup_run_dir(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(mod, "PROJECT_ROOT", tmp_path)
    parent = mod.resolve_backup_parent(None)
    run = mod.make_backup_run_dir(parent, "postgres", label="test")
    assert run.is_dir()
    assert run.name.startswith("postgres_")
    assert "test" in run.name


def test_missing_tool_message_includes_url() -> None:
    msg = mod.missing_tool_message("mongodump")
    assert "mongodump" in msg
    assert "mongodb.com" in msg


def test_tool_download_meta_for_mongodump() -> None:
    meta = mod._TOOL_DOWNLOAD["mongodump"]
    assert meta["url"].startswith("https://")
    assert meta["label"]


def test_list_and_delete_backup_runs(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(mod, "PROJECT_ROOT", tmp_path)
    parent = mod.resolve_backup_parent(None)
    run_a = mod.make_backup_run_dir(parent, "postgres", label="a")
    run_b = mod.make_backup_run_dir(parent, "mongodb", label="b")
    (run_a / "x.dump").write_bytes(b"12345")
    (run_b / "mongodb" / "c.bson").parent.mkdir(parents=True)
    (run_b / "mongodb" / "c.bson").write_bytes(b"abc")

    rows = mod.list_backup_runs()
    assert len(rows) == 2
    assert {r["name"] for r in rows} == {run_a.name, run_b.name}
    assert all(r["size_bytes"] > 0 for r in rows)

    out = mod.delete_backup_runs([str(run_a)])
    assert out["count"] == 1
    assert not run_a.exists()
    assert run_b.exists()


def test_delete_backup_runs_rejects_outside_parent(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(mod, "PROJECT_ROOT", tmp_path)
    parent = mod.resolve_backup_parent(None)
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "postgres_evil").mkdir()
    with pytest.raises(ValueError, match="不在允许"):
        mod.delete_backup_runs([str(outside / "postgres_evil")], output_parent=str(parent))


def test_browse_backup_directories(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(mod, "PROJECT_ROOT", tmp_path)
    child = mod.resolve_backup_parent(None)
    nested = child / "nested"
    nested.mkdir()
    data = mod.browse_backup_directories(path=str(child))
    assert data["current"] == str(child.resolve())
    assert any(entry["name"] == "nested" for entry in data["entries"])


def test_normalize_pg_tables_rejects_invalid() -> None:
    with pytest.raises(ValueError, match="无效"):
        mod.normalize_pg_tables(["bad-name"])
