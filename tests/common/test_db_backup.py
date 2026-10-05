from __future__ import annotations

import errno
import hashlib
import json
import os
import stat
from pathlib import Path
from types import SimpleNamespace

import pymongo
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
    (run_b / "mongodb" / "PallasBot").mkdir(parents=True)
    (run_b / "mongodb" / "PallasBot" / "c.bson").write_bytes(b"abc")

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


def test_browse_allowed_with_symlinked_default_parent(tmp_path, monkeypatch) -> None:
    external = tmp_path / "external_backups"
    external.mkdir()
    project = tmp_path / "project"
    project.mkdir()
    (project / "backups").symlink_to(external, target_is_directory=True)
    monkeypatch.setattr(mod, "PROJECT_ROOT", project)
    data = mod.browse_backup_directories(path=None)
    assert data["current"] == str(external.resolve())
    assert data["parent"] == str(tmp_path.resolve())


def test_browse_rejects_unrelated_dir_with_symlinked_default(tmp_path, monkeypatch) -> None:
    external = tmp_path / "external_backups"
    external.mkdir()
    project = tmp_path / "project"
    project.mkdir()
    (project / "backups").symlink_to(external, target_is_directory=True)
    monkeypatch.setattr(mod, "PROJECT_ROOT", project)
    unrelated = tmp_path / "unrelated"
    unrelated.mkdir()
    with pytest.raises(ValueError, match="不在允许范围"):
        mod.browse_backup_directories(path=str(unrelated))


def test_normalize_pg_tables_rejects_invalid() -> None:
    with pytest.raises(ValueError, match="无效"):
        mod.normalize_pg_tables(["bad-name"])


def test_postgres_tool_selection_prefers_server_major_and_allows_patch_minor(monkeypatch) -> None:
    paths = {name: [Path(f"/fake/{name}-14"), Path(f"/fake/{name}-18")] for name in ("pg_dump", "pg_restore")}
    versions = {
        Path("/fake/pg_dump-14"): ("14.24", 14),
        Path("/fake/pg_dump-18"): ("18.4", 18),
        Path("/fake/pg_restore-14"): ("14.24", 14),
        Path("/fake/pg_restore-18"): ("18.4", 18),
    }
    monkeypatch.setattr(mod, "pg_tool_candidates", lambda tool: paths[tool])
    monkeypatch.setattr(mod, "pg_tool_version", lambda path: versions[path])

    assert mod.select_pg_tool("pg_dump", 18) == (Path("/fake/pg_dump-18"), "18.4", 18)
    assert mod.select_pg_tool("pg_restore", 18, exact_major=True) == (
        Path("/fake/pg_restore-18"),
        "18.4",
        18,
    )
    assert mod.select_pg_tool("pg_dump", 17)[0] == Path("/fake/pg_dump-18")


def test_postgres_tool_selection_rejects_only_older_clients(monkeypatch) -> None:
    monkeypatch.setattr(mod, "pg_tool_candidates", lambda _tool: [Path("/fake/pg_dump-14")])
    monkeypatch.setattr(mod, "pg_tool_version", lambda _path: ("14.24", 14))

    with pytest.raises(RuntimeError, match="兼容"):
        mod.select_pg_tool("pg_dump", 18)


def test_incompatible_pg_dump_is_rejected_before_execution(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(mod, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(mod, "postgres_server_info", lambda: (18, "18.3"))
    monkeypatch.setattr(mod, "pg_tool_candidates", lambda _tool: [Path("/fake/pg_dump-14")])
    monkeypatch.setattr(mod, "pg_tool_version", lambda _path: ("14.24", 14))
    calls: list[list[str]] = []
    monkeypatch.setattr(mod, "_run_checked", lambda cmd, **_kwargs: calls.append(cmd))

    with pytest.raises(RuntimeError, match="兼容"):
        mod.run_postgres_backup(output_parent=str(tmp_path / "backups"))
    assert calls == []
    assert not list((tmp_path / "backups").glob("postgres_*"))


def test_postgres_tool_candidates_search_path_pg_config_and_debian(tmp_path, monkeypatch) -> None:
    path_tool = tmp_path / "path" / "pg_dump"
    config_tool = tmp_path / "configured" / "pg_dump"
    debian_tool = tmp_path / "debian" / "pg_dump"
    for tool in (path_tool, config_tool, debian_tool):
        tool.parent.mkdir(parents=True, exist_ok=True)
        tool.write_text("tool")
        tool.chmod(0o755)
    pg_config = tmp_path / "pg_config"
    pg_config.write_text("pg_config")
    pg_config.chmod(0o755)
    monkeypatch.setenv("PATH", str(path_tool.parent))
    monkeypatch.setattr(
        mod.shutil,
        "which",
        lambda name: str(path_tool) if name == "pg_dump" else str(pg_config) if name == "pg_config" else None,
    )
    monkeypatch.setattr(
        mod.subprocess,
        "run",
        lambda *_args, **_kwargs: SimpleNamespace(returncode=0, stdout=str(config_tool.parent), stderr=""),
    )
    monkeypatch.setattr(Path, "glob", lambda _path, _pattern: [debian_tool.parent])

    assert mod.pg_tool_candidates("pg_dump") == [path_tool.resolve(), config_tool.resolve(), debian_tool.resolve()]


def test_postgres_tool_version_reads_major_and_patch(monkeypatch) -> None:
    monkeypatch.setattr(
        mod.subprocess,
        "run",
        lambda *_args, **_kwargs: SimpleNamespace(returncode=0, stdout="pg_dump (PostgreSQL) 18.4", stderr=""),
    )

    assert mod.pg_tool_version(Path("/fake/pg_dump")) == ("18.4", 18)


def test_postgres_server_info_uses_timed_read_only_psql(monkeypatch) -> None:
    calls: list[list[str]] = []
    outputs = iter(("180003\n",))
    monkeypatch.setattr(mod, "select_pg_tool", lambda *_args, **_kwargs: (Path("/fake/psql"), "18.4", 18))
    monkeypatch.setattr(mod, "_cfg", lambda _key, default="": default)

    def run(cmd, **kwargs):
        calls.append(cmd)
        assert kwargs["timeout"] == 10
        assert kwargs["env"]["PGCONNECT_TIMEOUT"] == "5"
        return SimpleNamespace(returncode=0, stdout=next(outputs), stderr="")

    monkeypatch.setattr(mod.subprocess, "run", run)

    assert mod.postgres_server_info() == (18, "18.3")
    assert all("-X" in cmd and "-A" in cmd and "-t" in cmd and "-w" in cmd for cmd in calls)
    assert calls[0][-2:] == ["-c", "SHOW server_version_num"]
    assert len(calls) == 1


def test_mongodb_server_info_does_not_query_database_size(monkeypatch) -> None:
    class FakeClient:
        admin = SimpleNamespace(command=lambda name: {"version": "8.0.1"} if name == "buildInfo" else pytest.fail(name))

        def __getitem__(self, _name):
            return self

        def command(self, name, **_kwargs):
            pytest.fail(f"unexpected MongoDB probe: {name}")

        def close(self) -> None:
            pass

    monkeypatch.setattr(pymongo, "MongoClient", lambda *_args, **_kwargs: FakeClient())
    monkeypatch.setattr(mod, "_cfg", lambda _key, default="": default)

    assert mod.mongo_server_info() == "8.0.1"


def test_backup_info_does_not_probe_postgres_server(monkeypatch) -> None:
    monkeypatch.setattr(mod, "get_db_backend", lambda: "postgresql")
    monkeypatch.setattr(mod, "_cfg", lambda _key, default="": default)
    monkeypatch.setattr(mod, "_pg_host", lambda: "localhost")
    monkeypatch.setattr(
        mod,
        "select_pg_tool",
        lambda tool, *_args, **_kwargs: (Path(f"/fake/{tool}"), "18.4", 18),
    )
    monkeypatch.setattr(mod, "postgres_server_info", lambda: pytest.fail("backup_info queried the server"))

    info = mod.backup_info()
    assert info["tool_available"]
    assert info["restore_tool_available"]


@pytest.mark.parametrize("pg_format", ["custom", "plain", "directory"])
def test_postgres_backup_publishes_validated_manifest(tmp_path, monkeypatch, pg_format) -> None:
    monkeypatch.setattr(mod, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(mod, "postgres_server_info", lambda: (18, "18.3"))
    monkeypatch.setattr(
        mod,
        "select_pg_tool",
        lambda tool, *_args, **_kwargs: (Path(f"/fake/{tool}"), "18.4", 18),
    )
    commands: list[list[str]] = []

    def run_checked(cmd, **_kwargs):
        commands.append(cmd)
        if cmd[0].endswith("pg_dump"):
            if "-f" in cmd:
                output = Path(cmd[cmd.index("-f") + 1])
                if "-Fd" in cmd:
                    output.mkdir(parents=True, exist_ok=True)
                    (output / "toc.dat").write_bytes(b"toc")
                    (output / "data.dat").write_bytes(b"archive")
                elif output.suffix == ".sql":
                    output.write_bytes(b"-- PostgreSQL database dump complete\n\\unrestrict token\n")
                else:
                    output.write_bytes(b"archive")

    monkeypatch.setattr(mod, "_run_checked", run_checked)
    result = mod.run_postgres_backup(output_parent=str(tmp_path / "backups"), pg_format=pg_format)

    published = Path(result.output_dir)
    assert published.name.startswith("postgres_")
    assert not published.name.startswith(".")
    assert Path(result.artifacts[0]).exists()
    assert stat.S_IMODE(published.stat().st_mode) == 0o700
    for child in published.rglob("*"):
        assert stat.S_IMODE(child.stat().st_mode) == (0o700 if child.is_dir() else 0o600)
    manifest = json.loads((published / mod._BACKUP_MANIFEST_NAME).read_text())
    assert manifest["schema"] == mod._BACKUP_MANIFEST_SCHEMA
    assert manifest["server_version"] == "18.3"
    assert manifest["tool"] == {"name": "pg_dump", "version": "18.4"}
    if pg_format != "plain":
        assert manifest["validation_method"] == "archive_read_check"
        archive_check = next(cmd for cmd in commands if cmd[0].endswith("pg_restore"))
        assert archive_check[archive_check.index("--file") + 1] == mod.os.devnull
        assert "--list" not in archive_check
        assert "-d" not in archive_check
        assert "-h" not in archive_check
    if pg_format == "custom":
        assert manifest["files"] == [
            {
                "path": "PallasBot.dump",
                "size_bytes": 7,
                "sha256": hashlib.sha256(b"archive").hexdigest(),
            }
        ]
    listed = mod.list_backup_runs(output_parent=str(tmp_path / "backups"))
    assert [row["path"] for row in listed] == [str(published)]


def test_postgres_second_table_failure_never_publishes(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(mod, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(mod, "postgres_server_info", lambda: (18, "18.3"))
    monkeypatch.setattr(
        mod,
        "select_pg_tool",
        lambda tool, *_args, **_kwargs: (Path(f"/fake/{tool}"), "18.4", 18),
    )
    dump_count = 0

    def run_checked(cmd, **_kwargs):
        nonlocal dump_count
        if cmd[0].endswith("pg_dump"):
            dump_count += 1
            Path(cmd[cmd.index("-f") + 1]).write_bytes(b"partial")
            if dump_count == 2:
                raise OSError(errno.ENOSPC, "No space left on device")

    monkeypatch.setattr(mod, "_run_checked", run_checked)
    parent = tmp_path / "backups"
    with pytest.raises(RuntimeError, match="空间不足"):
        mod.run_postgres_backup(output_parent=str(parent), pg_tables=["one", "two"])

    assert list(parent.glob("postgres_*")) == []
    assert list(parent.glob(".*.staging-*")) == []


def test_postgres_archive_validation_failure_is_not_published(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(mod, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(mod, "postgres_server_info", lambda: (18, "18.3"))
    monkeypatch.setattr(
        mod,
        "select_pg_tool",
        lambda tool, *_args, **_kwargs: (Path(f"/fake/{tool}"), "18.4", 18),
    )

    def run_checked(cmd, **_kwargs):
        if cmd[0].endswith("pg_dump"):
            Path(cmd[cmd.index("-f") + 1]).write_bytes(b"archive")
        elif "--file" in cmd:
            raise RuntimeError("bad archive")

    monkeypatch.setattr(mod, "_run_checked", run_checked)
    parent = tmp_path / "backups"
    with pytest.raises(RuntimeError, match="bad archive"):
        mod.run_postgres_backup(output_parent=str(parent))

    assert list(parent.glob("postgres_*")) == []


def test_plain_dump_without_completion_marker_is_not_published(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(mod, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(mod, "postgres_server_info", lambda: (18, "18.3"))
    monkeypatch.setattr(
        mod,
        "select_pg_tool",
        lambda tool, *_args, **_kwargs: (Path(f"/fake/{tool}"), "18.4", 18),
    )
    monkeypatch.setattr(
        mod,
        "_run_checked",
        lambda cmd, **_kwargs: (
            Path(cmd[cmd.index("-f") + 1]).write_bytes(b"incomplete SQL") if cmd[0].endswith("pg_dump") else None
        ),
    )
    parent = tmp_path / "backups"
    with pytest.raises(ValueError, match="完成标记"):
        mod.run_postgres_backup(output_parent=str(parent), pg_format="plain")
    assert list(parent.glob("postgres_*")) == []


def test_publish_rename_failure_cleans_staging(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(mod, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(mod, "postgres_server_info", lambda: (18, "18.3"))
    monkeypatch.setattr(
        mod,
        "select_pg_tool",
        lambda tool, *_args, **_kwargs: (Path(f"/fake/{tool}"), "18.4", 18),
    )
    monkeypatch.setattr(
        mod,
        "_run_checked",
        lambda cmd, **_kwargs: (
            Path(cmd[cmd.index("-f") + 1]).write_bytes(b"archive") if cmd[0].endswith("pg_dump") else None
        ),
    )
    original_rename = Path.rename

    def fail_publish(path: Path, target: Path):
        if mod._staging_target(path) is not None:
            raise OSError(errno.ENOSPC, "No space left on device")
        return original_rename(path, target)

    monkeypatch.setattr(Path, "rename", fail_publish)
    parent = tmp_path / "backups"
    with pytest.raises(RuntimeError, match="空间不足"):
        mod.run_postgres_backup(output_parent=str(parent))
    assert list(parent.glob("postgres_*")) == []
    assert list(parent.glob(".*.staging-*")) == []


def test_list_backup_runs_excludes_empty_and_hidden_staging_but_keeps_legacy(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(mod, "PROJECT_ROOT", tmp_path)
    parent = mod.resolve_backup_parent(None)
    (parent / "postgres_empty").mkdir()
    (parent / ".pallas-backup-postgres_partial.staging-x").mkdir()
    failed = parent / "postgres_failed"
    failed.mkdir()
    (failed / "partial.sql").write_text("incomplete")
    legacy = parent / "postgres_legacy"
    legacy.mkdir()
    (legacy / "old.dump").write_bytes(b"old archive")
    (legacy / mod._BACKUP_MANIFEST_NAME).write_text('{"manual": true}')

    assert [row["name"] for row in mod.list_backup_runs()] == ["postgres_legacy"]
    assert not mod._verify_backup_manifest(legacy)


def test_manifest_detects_tampering_escape_and_unregistered_files(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(mod, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(mod, "postgres_server_info", lambda: (18, "18.3"))
    monkeypatch.setattr(
        mod,
        "select_pg_tool",
        lambda tool, *_args, **_kwargs: (Path(f"/fake/{tool}"), "18.4", 18),
    )
    monkeypatch.setattr(
        mod,
        "_run_checked",
        lambda cmd, **_kwargs: (
            Path(cmd[cmd.index("-f") + 1]).write_bytes(b"archive") if cmd[0].endswith("pg_dump") else None
        ),
    )
    run = Path(mod.run_postgres_backup(output_parent=str(tmp_path / "backups")).output_dir)
    artifact = run / "PallasBot.dump"
    artifact.write_bytes(b"tampered")
    with pytest.raises(ValueError, match="校验"):
        mod._verify_backup_manifest(run)

    artifact.write_bytes(b"archive")
    (run / "extra.txt").write_text("extra")
    with pytest.raises(ValueError, match="清单"):
        mod._verify_backup_manifest(run)

    manifest_path = run / mod._BACKUP_MANIFEST_NAME
    manifest = json.loads(manifest_path.read_text())
    manifest["files"][0]["path"] = "../outside.dump"
    manifest_path.write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="路径"):
        mod._verify_backup_manifest(run)


def test_download_and_restore_reject_modified_new_manifest_backup(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(mod, "PROJECT_ROOT", tmp_path)
    parent = mod.resolve_backup_parent(None)
    run = parent / "postgres_integrity"
    run.mkdir()
    artifact = run / "db.dump"
    artifact.write_bytes(b"valid archive")
    mod._write_backup_manifest(
        run,
        backend="postgres",
        backup_format="custom",
        scope="custom",
        tool_name="pg_dump",
        tool_version="18.4",
        server_version="18.3",
        validation_method="archive_read_check",
    )
    artifact.write_bytes(b"modified archive")
    monkeypatch.setattr(mod, "postgres_server_info", lambda: pytest.fail("restore reached server probe"))

    with pytest.raises(ValueError, match="校验失败"):
        mod.prepare_backup_download(str(run))
    with pytest.raises(ValueError, match="校验失败"):
        mod.run_postgres_restore(run_dir=run)


def test_explicit_empty_run_dir_is_published_and_nonempty_is_preserved(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(mod, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(mod, "postgres_server_info", lambda: (18, "18.3"))
    monkeypatch.setattr(
        mod,
        "select_pg_tool",
        lambda tool, *_args, **_kwargs: (Path(f"/fake/{tool}"), "18.4", 18),
    )
    monkeypatch.setattr(
        mod,
        "_run_checked",
        lambda cmd, **_kwargs: (
            Path(cmd[cmd.index("-f") + 1]).write_bytes(b"archive") if cmd[0].endswith("pg_dump") else None
        ),
    )
    parent = tmp_path / "backups"
    visible = parent / "postgres_explicit"
    visible.mkdir(parents=True)
    result = mod.run_postgres_backup(output_parent=str(parent), run_dir=visible)
    assert Path(result.output_dir) == visible
    assert (visible / "PallasBot.dump").is_file()

    (visible / "keep.txt").write_text("keep")
    with pytest.raises(ValueError, match="空"):
        mod.run_postgres_backup(output_parent=str(parent), run_dir=visible)
    assert (visible / "keep.txt").read_text() == "keep"


def test_failed_backup_preserves_explicit_empty_target_without_staging_artifacts(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(mod, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(mod, "postgres_server_info", lambda: (18, "18.3"))
    monkeypatch.setattr(mod, "select_pg_tool", lambda tool, *_args, **_kwargs: (Path(f"/fake/{tool}"), "18.4", 18))
    monkeypatch.setattr(
        mod, "_run_checked", lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("dump failed"))
    )
    parent = tmp_path / "backups"
    visible = parent / "postgres_explicit"
    visible.mkdir(parents=True)

    with pytest.raises(RuntimeError, match="dump failed"):
        mod.run_postgres_backup(output_parent=str(parent), run_dir=visible)

    assert visible.is_dir()
    assert list(visible.iterdir()) == []
    assert list(parent.glob(".*.staging-*")) == []


def test_postgres_restore_preflights_every_archive_before_restoring(tmp_path, monkeypatch) -> None:
    run = tmp_path / "postgres_restore"
    run.mkdir()
    (run / "first.dump").write_bytes(b"first")
    (run / "second.dump").write_bytes(b"second")
    restore = Path("/fake/pg_restore")
    monkeypatch.setattr(mod, "pg_tool_candidates", lambda _tool: [restore])
    monkeypatch.setattr(mod, "pg_tool_version", lambda _path: ("18.4", 18))
    checked: list[list[str]] = []

    def run_checked(cmd, **_kwargs):
        checked.append(cmd)
        if "--file" in cmd and cmd[-1].endswith("second.dump"):
            raise RuntimeError("second archive damaged")

    monkeypatch.setattr(mod, "_run_checked", run_checked)
    with pytest.raises(RuntimeError, match="second archive"):
        mod.run_postgres_restore(run_dir=run)

    assert sum("--file" in cmd for cmd in checked) == 2
    assert not any("--clean" in cmd for cmd in checked)


def test_mongodb_backup_publishes_empty_bson_and_manifest(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(mod, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(mod, "tool_on_path", lambda _tool: True)
    monkeypatch.setattr(mod, "_cfg", lambda _key, default="": default)
    monkeypatch.setattr(mod, "_command_version", lambda _tool: "100.13.0")
    monkeypatch.setattr(mod, "mongo_server_info", lambda: "8.0.1")

    def run_checked(cmd, **_kwargs):
        root = Path(cmd[cmd.index("-o") + 1]) / "PallasBot"
        root.mkdir(parents=True, exist_ok=True)
        (root / "empty.bson").touch()
        (root / "empty.metadata.json").write_text("{}")

    monkeypatch.setattr(mod, "_run_checked", run_checked)
    result = mod.run_mongodb_backup(output_parent=str(tmp_path / "backups"), mongo_collections=["empty"])

    run = Path(result.output_dir)
    assert (run / "mongodb" / "PallasBot" / "empty.bson").stat().st_size == 0
    assert stat.S_IMODE(run.stat().st_mode) == 0o700
    for child in run.rglob("*"):
        assert stat.S_IMODE(child.stat().st_mode) == (0o700 if child.is_dir() else 0o600)
    assert mod._verify_backup_manifest(run)
    assert [row["path"] for row in mod.list_backup_runs(output_parent=str(tmp_path / "backups"))] == [str(run)]


def test_mongodb_partial_failure_is_not_published(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(mod, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(mod, "tool_on_path", lambda _tool: True)
    monkeypatch.setattr(mod, "_cfg", lambda _key, default="": default)
    monkeypatch.setattr(mod, "_command_version", lambda _tool: "100.13.0")
    monkeypatch.setattr(mod, "mongo_server_info", lambda: "8.0.1")
    calls = 0

    def run_checked(cmd, **_kwargs):
        nonlocal calls
        calls += 1
        root = Path(cmd[cmd.index("-o") + 1]) / "PallasBot"
        root.mkdir(parents=True, exist_ok=True)
        (root / f"{calls}.bson").touch()
        if calls == 2:
            raise RuntimeError("second collection failed")

    monkeypatch.setattr(mod, "_run_checked", run_checked)
    parent = tmp_path / "backups"
    with pytest.raises(RuntimeError, match="second collection"):
        mod.run_mongodb_backup(output_parent=str(parent), scope="important")

    assert list(parent.glob("mongodb_*")) == []
    assert list(parent.glob(".*.staging-*")) == []


def test_external_hidden_staging_outside_parent_is_rejected_without_removal(tmp_path, monkeypatch) -> None:
    parent = tmp_path / "backups"
    parent.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    staging = outside / ".postgres_valuable.staging-x"
    staging.mkdir()
    sentinel = staging / "keep.txt"
    sentinel.write_text("valuable")
    monkeypatch.setattr(mod, "get_db_backend", lambda: "postgresql")
    monkeypatch.setattr(mod, "postgres_server_info", lambda: pytest.fail("invalid path reached server probe"))

    with pytest.raises(ValueError, match="目标文件系统"):
        mod.run_database_backup(output_parent=str(parent), run_dir=staging)

    assert sentinel.read_text() == "valuable"


def test_nonempty_hidden_staging_input_is_rejected_without_removal(tmp_path, monkeypatch) -> None:
    parent = tmp_path / "backups"
    staging = parent / ".postgres_target.staging-x"
    staging.mkdir(parents=True)
    sentinel = staging / "keep.txt"
    sentinel.write_text("valuable")
    monkeypatch.setattr(mod, "postgres_server_info", lambda: (18, "18.3"))
    monkeypatch.setattr(mod, "select_pg_tool", lambda tool, *_args, **_kwargs: (Path(f"/fake/{tool}"), "18.4", 18))

    with pytest.raises(ValueError, match="空"):
        mod.run_postgres_backup(output_parent=str(parent), run_dir=staging)

    assert sentinel.read_text() == "valuable"


def test_existing_hidden_staging_target_does_not_delete_input(tmp_path, monkeypatch) -> None:
    parent = tmp_path / "backups"
    staging = parent / ".postgres_existing.staging-x"
    staging.mkdir(parents=True)
    target = parent / "postgres_existing"
    target.mkdir()
    (target / "keep.txt").write_text("existing backup")
    monkeypatch.setattr(mod, "postgres_server_info", lambda: pytest.fail("collision reached server probe"))

    with pytest.raises(FileExistsError, match="已存在"):
        mod.run_postgres_backup(output_parent=str(parent), run_dir=staging)

    assert staging.is_dir()
    assert (target / "keep.txt").read_text() == "existing backup"


def test_probe_failure_keeps_caller_staging_directory(tmp_path, monkeypatch) -> None:
    parent = tmp_path / "backups"
    staging = parent / ".postgres_target.staging-x"
    staging.mkdir(parents=True)
    monkeypatch.setattr(mod, "get_db_backend", lambda: "postgresql")
    monkeypatch.setattr(mod, "postgres_server_info", lambda: (_ for _ in ()).throw(RuntimeError("probe failed")))

    with pytest.raises(RuntimeError, match="probe failed"):
        mod.run_database_backup(output_parent=str(parent), run_dir=staging)

    assert staging.is_dir()


def test_symlink_staging_input_is_rejected_without_removing_target(tmp_path, monkeypatch) -> None:
    parent = tmp_path / "backups"
    parent.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    target = outside / ".postgres_valuable.staging-x"
    target.mkdir()
    sentinel = target / "keep.txt"
    sentinel.write_text("valuable")
    link = parent / ".postgres_valuable.staging-x"
    link.symlink_to(target, target_is_directory=True)
    monkeypatch.setattr(mod, "get_db_backend", lambda: "postgresql")
    monkeypatch.setattr(mod, "postgres_server_info", lambda: (_ for _ in ()).throw(RuntimeError("probe failed")))

    with pytest.raises(ValueError, match="符号链接"):
        mod.run_database_backup(output_parent=str(parent), run_dir=link)

    assert link.is_symlink()
    assert sentinel.read_text() == "valuable"


@pytest.mark.parametrize("failure", ["probe", "backup", "validation"])
def test_postgres_backup_failures_do_not_publish(tmp_path, monkeypatch, failure) -> None:
    monkeypatch.setattr(mod, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(mod, "postgres_server_info", lambda: (18, "18.3"))
    monkeypatch.setattr(mod, "select_pg_tool", lambda tool, *_args, **_kwargs: (Path(f"/fake/{tool}"), "18.4", 18))
    monkeypatch.setattr(
        mod.shutil, "disk_usage", lambda _path: SimpleNamespace(total=30 * 1024**3, used=25 * 1024**3, free=5 * 1024**3)
    )

    def run_checked(cmd, **_kwargs):
        if cmd[0].endswith("pg_dump"):
            Path(cmd[cmd.index("-f") + 1]).write_bytes(b"compressed dump")
            if failure == "backup":
                raise RuntimeError("dump failed")
        elif "--file" in cmd and failure == "validation":
            raise RuntimeError("archive validation failed")

    monkeypatch.setattr(mod, "_run_checked", run_checked)
    parent = tmp_path / "backups"
    if failure == "probe":
        monkeypatch.setattr(mod, "postgres_server_info", lambda: (_ for _ in ()).throw(RuntimeError("probe failed")))
        expected_error = "probe failed"
    else:
        expected_error = "dump failed" if failure == "backup" else "archive validation failed"
    with pytest.raises(RuntimeError, match=expected_error):
        mod.run_postgres_backup(output_parent=str(parent))
    assert list(parent.glob("postgres_*")) == []
    assert list(parent.glob(".*.staging-*")) == []


@pytest.mark.parametrize("pg_tables", [None, ["selected"]])
def test_compressed_postgres_backup_does_not_require_physical_database_size(tmp_path, monkeypatch, pg_tables) -> None:
    monkeypatch.setattr(mod, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(mod, "postgres_server_info", lambda: (18, "18.3"))
    monkeypatch.setattr(mod, "select_pg_tool", lambda tool, *_args, **_kwargs: (Path(f"/fake/{tool}"), "18.4", 18))
    monkeypatch.setattr(
        mod.shutil, "disk_usage", lambda _path: SimpleNamespace(total=30 * 1024**3, used=25 * 1024**3, free=5 * 1024**3)
    )
    monkeypatch.setattr(
        mod,
        "_run_checked",
        lambda cmd, **_kwargs: (
            Path(cmd[cmd.index("-f") + 1]).write_bytes(b"compressed dump") if cmd[0].endswith("pg_dump") else None
        ),
    )

    result = mod.run_postgres_backup(output_parent=str(tmp_path / "backups"), pg_tables=pg_tables)

    assert Path(result.output_dir).is_dir()


def test_zero_free_target_space_is_rejected(tmp_path, monkeypatch) -> None:
    staging = tmp_path / ".postgres_test.staging-x"
    staging.mkdir()
    monkeypatch.setattr(mod.shutil, "disk_usage", lambda _path: SimpleNamespace(total=1, used=1, free=0))

    with pytest.raises(RuntimeError, match="磁盘空间不足"):
        mod._check_backup_target(staging)


def test_mongodb_collection_backup_does_not_require_full_database_size(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(mod, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(mod, "tool_on_path", lambda _tool: True)
    monkeypatch.setattr(mod, "_cfg", lambda _key, default="": default)
    monkeypatch.setattr(mod, "_command_version", lambda _tool: "100.13.0")
    monkeypatch.setattr(mod, "mongo_server_info", lambda: "8.0.1")
    monkeypatch.setattr(
        mod.shutil, "disk_usage", lambda _path: SimpleNamespace(total=30 * 1024**3, used=25 * 1024**3, free=5 * 1024**3)
    )

    def run_checked(cmd, **_kwargs):
        root = Path(cmd[cmd.index("-o") + 1]) / "PallasBot"
        root.mkdir(parents=True, exist_ok=True)
        (root / "selected.bson").write_bytes(b"small selected collection")

    monkeypatch.setattr(mod, "_run_checked", run_checked)
    result = mod.run_mongodb_backup(output_parent=str(tmp_path / "backups"), mongo_collections=["selected"])

    assert Path(result.output_dir).is_dir()


@pytest.mark.parametrize("tool", ["pg_dump", "pg_restore"])
def test_pg_tool_candidate_preserves_basename_sensitive_path(tmp_path, monkeypatch, tool) -> None:
    invocation = tmp_path / "bin" / tool
    implementation = tmp_path / "bin" / "pg_wrapper"
    invocation.parent.mkdir()
    implementation.write_text("wrapper")
    implementation.chmod(0o755)
    invocation.symlink_to(implementation)
    monkeypatch.setenv("PATH", str(invocation.parent))
    monkeypatch.setattr(mod.shutil, "which", lambda name: str(invocation) if name == tool else None)
    monkeypatch.setattr(Path, "glob", lambda _path, _pattern: [])
    calls: list[list[str]] = []

    def run(cmd, **_kwargs):
        calls.append(cmd)
        basename = Path(cmd[0]).name
        return SimpleNamespace(returncode=0 if basename == tool else 1, stdout="(PostgreSQL) 18.4", stderr="")

    monkeypatch.setattr(mod.subprocess, "run", run)

    candidates = mod.pg_tool_candidates(tool)
    assert candidates == [invocation]
    assert mod.pg_tool_version(candidates[0]) == ("18.4", 18)
    assert calls[0][0] == str(invocation)


def test_pg_tool_candidates_keep_which_exe_when_extensionless_path_missing(tmp_path, monkeypatch) -> None:
    exe = tmp_path / "pg_dump.exe"
    exe.write_text("windows tool")
    exe.chmod(0o755)
    monkeypatch.setenv("PATH", str(tmp_path))
    monkeypatch.setattr(mod.shutil, "which", lambda name: str(exe) if name == "pg_dump" else None)
    monkeypatch.setattr(Path, "glob", lambda _path, _pattern: [])

    assert mod.pg_tool_candidates("pg_dump") == [exe]


def test_postgres_tool_selection_prefers_newest_minor(monkeypatch) -> None:
    versions = {
        Path("/fake/pg_dump-18.3"): ("18.3", 18),
        Path("/fake/pg_dump-18.4"): ("18.4", 18),
    }
    monkeypatch.setattr(mod, "pg_tool_candidates", lambda _tool: list(versions))
    monkeypatch.setattr(mod, "pg_tool_version", lambda path: versions[path])

    assert mod.select_pg_tool("pg_dump", 18) == (Path("/fake/pg_dump-18.4"), "18.4", 18)


def test_postgres_restore_tries_latest_reader_without_probing_target_server(tmp_path, monkeypatch) -> None:
    run = tmp_path / "postgres_restore"
    run.mkdir()
    (run / "db.dump").write_bytes(b"archive")
    tools = [Path("/fake/pg_restore-14"), Path("/fake/pg_restore-18")]
    versions = {tools[0]: ("14.24", 14), tools[1]: ("18.4", 18)}
    monkeypatch.setattr(mod, "pg_tool_candidates", lambda _tool: tools)
    monkeypatch.setattr(mod, "pg_tool_version", lambda path: versions[path])
    monkeypatch.setattr(mod, "postgres_server_info", lambda: (14, "14.12"))
    commands: list[list[str]] = []
    monkeypatch.setattr(mod, "_run_checked", lambda cmd, **_kwargs: commands.append(cmd))

    result = mod.run_postgres_restore(run_dir=run)

    assert result.ok
    assert commands[0][0] == str(tools[1])
    assert "--file" in commands[0]
    assert commands[1][0] == str(tools[1])
    assert "--clean" in commands[1]


def test_postgres_restore_falls_back_when_latest_reader_rejects_archive(tmp_path, monkeypatch) -> None:
    run = tmp_path / "postgres_restore"
    run.mkdir()
    (run / "db.dump").write_bytes(b"archive")
    tools = [Path("/fake/pg_restore-14"), Path("/fake/pg_restore-18")]
    versions = {tools[0]: ("14.24", 14), tools[1]: ("18.4", 18)}
    monkeypatch.setattr(mod, "pg_tool_candidates", lambda _tool: tools)
    monkeypatch.setattr(mod, "pg_tool_version", lambda path: versions[path])
    monkeypatch.setattr(mod, "postgres_server_info", lambda: pytest.fail("restore queried target server"))
    commands: list[list[str]] = []

    def run_checked(cmd, **_kwargs):
        commands.append(cmd)
        if "--file" in cmd and cmd[0] == str(tools[1]):
            raise RuntimeError("newest reader rejects archive")

    monkeypatch.setattr(mod, "_run_checked", run_checked)

    result = mod.run_postgres_restore(run_dir=run)

    assert result.ok
    assert [cmd[0] for cmd in commands] == [str(tools[1]), str(tools[0]), str(tools[0])]
    assert "--clean" in commands[-1]


def test_postgres_restore_never_modifies_target_if_no_reader_can_read_archive(tmp_path, monkeypatch) -> None:
    run = tmp_path / "postgres_restore"
    run.mkdir()
    (run / "db.dump").write_bytes(b"archive")
    tools = [Path("/fake/pg_restore-14"), Path("/fake/pg_restore-18")]
    versions = {tools[0]: ("14.24", 14), tools[1]: ("18.4", 18)}
    monkeypatch.setattr(mod, "pg_tool_candidates", lambda _tool: tools)
    monkeypatch.setattr(mod, "pg_tool_version", lambda path: versions[path])
    monkeypatch.setattr(mod, "postgres_server_info", lambda: pytest.fail("restore queried target server"))
    commands: list[list[str]] = []

    def run_checked(cmd, **_kwargs):
        commands.append(cmd)
        raise RuntimeError("archive format unsupported")

    monkeypatch.setattr(mod, "_run_checked", run_checked)
    with pytest.raises(RuntimeError, match="读取"):
        mod.run_postgres_restore(run_dir=run)

    assert [cmd[0] for cmd in commands] == [str(tools[1]), str(tools[0])]
    assert all("--clean" not in cmd for cmd in commands)


def test_postgres_backup_rejects_symlink_and_special_outputs_before_chmod(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(mod, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(mod, "postgres_server_info", lambda: (18, "18.3"))
    monkeypatch.setattr(mod, "select_pg_tool", lambda tool, *_args, **_kwargs: (Path(f"/fake/{tool}"), "18.4", 18))
    outside = tmp_path / "outside.txt"
    outside.write_text("keep")
    outside.chmod(0o644)

    def run_checked(cmd, **_kwargs):
        if cmd[0].endswith("pg_dump"):
            output = Path(cmd[cmd.index("-f") + 1])
            output.symlink_to(outside)

    monkeypatch.setattr(mod, "_run_checked", run_checked)
    with pytest.raises(ValueError, match="符号链接"):
        mod.run_postgres_backup(output_parent=str(tmp_path / "backups"))
    assert outside.read_text() == "keep"
    assert stat.S_IMODE(outside.stat().st_mode) == 0o644


def test_postgres_backup_rejects_special_files(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(mod, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(mod, "postgres_server_info", lambda: (18, "18.3"))
    monkeypatch.setattr(mod, "select_pg_tool", lambda tool, *_args, **_kwargs: (Path(f"/fake/{tool}"), "18.4", 18))

    def run_checked(cmd, **_kwargs):
        if cmd[0].endswith("pg_dump"):
            output = Path(cmd[cmd.index("-f") + 1])
            output.mkdir()
            (output / "toc.dat").write_bytes(b"toc")
            os.mkfifo(output / "unknown.pipe")

    monkeypatch.setattr(mod, "_run_checked", run_checked)
    with pytest.raises(ValueError, match="不支持"):
        mod.run_postgres_backup(output_parent=str(tmp_path / "backups"), pg_format="directory")
