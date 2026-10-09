from __future__ import annotations

import asyncio
import importlib
import stat
from typing import TYPE_CHECKING

import pytest
from starlette.background import BackgroundTask

from pallas.core.foundation.db import backup

if TYPE_CHECKING:
    from pathlib import Path


def _make_legacy_run(tmp_path, monkeypatch) -> tuple[Path, Path]:
    monkeypatch.setattr(backup, "PROJECT_ROOT", tmp_path)
    parent = backup.resolve_backup_parent(None)
    run = parent / "postgres_legacy"
    run.mkdir()
    (run / "database.dump").write_bytes(b"archive")
    return parent, run


def test_backup_download_uses_hidden_parent_tempdir_and_cleanup(tmp_path, monkeypatch) -> None:
    parent, run = _make_legacy_run(tmp_path, monkeypatch)
    artifact = run / "database.dump"
    artifact.chmod(0o640)

    zip_path, filename = backup.prepare_backup_download(str(run))

    assert zip_path.parent.parent == parent
    assert zip_path.parent.name.startswith(".pallas-backup-download-")
    assert filename == "postgres_legacy.zip"
    assert stat.S_IMODE(zip_path.stat().st_mode) == 0o600
    assert stat.S_IMODE(artifact.stat().st_mode) == 0o640
    assert not backup.list_backup_runs()[0]["name"].startswith(".pallas-backup-download-")
    backup.cleanup_backup_download(zip_path)
    assert not zip_path.parent.exists()


def test_backup_download_pack_failure_removes_partial_zip(tmp_path, monkeypatch) -> None:
    _parent, run = _make_legacy_run(tmp_path, monkeypatch)

    class BrokenZip:
        def __init__(self, *_args, **_kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def write(self, *_args):
            raise OSError("pack failed")

    monkeypatch.setattr(backup.zipfile, "ZipFile", BrokenZip)
    with pytest.raises(OSError, match="pack failed"):
        backup.prepare_backup_download(str(run))
    assert not list(run.parent.glob(".pallas-backup-download-*"))


@pytest.mark.parametrize(("range_header", "fail_send"), [(None, False), (None, True), (b"bytes=0-2", True)])
def test_backup_response_removes_zip_after_success_send_failure_and_range(
    tmp_path, range_header, fail_send, isolated_nonebot_plugin_state
) -> None:
    db_api = importlib.import_module("packages.pb_webui.db_api")
    work = tmp_path / ".pallas-backup-download-test"
    work.mkdir(mode=0o700)
    zip_path = work / "backup.zip"
    zip_path.write_bytes(b"zip contents")
    response = db_api._BackupDownloadResponse(
        zip_path,
        filename="backup.zip",
        media_type="application/zip",
        background=BackgroundTask(backup.cleanup_backup_download, zip_path),
    )
    headers = [] if range_header is None else [(b"range", range_header)]
    scope = {"type": "http", "method": "GET", "path": "/download", "headers": headers}

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message):
        if fail_send and message["type"] == "http.response.body":
            raise OSError("client disconnected")

    if fail_send:
        with pytest.raises(OSError, match="client disconnected"):
            asyncio.run(response(scope, receive, send))
    else:
        asyncio.run(response(scope, receive, send))
    assert not zip_path.exists()
    assert not work.exists()


def test_cancelled_download_cleans_worker_result(monkeypatch, tmp_path, isolated_nonebot_plugin_state) -> None:
    db_api = importlib.import_module("packages.pb_webui.db_api")
    work = tmp_path / ".pallas-backup-download-cancel"
    work.mkdir(mode=0o700)
    zip_path = work / "backup.zip"
    entered = asyncio.Event()
    release = asyncio.Event()
    cleaned = asyncio.Event()
    real_cleanup = backup.cleanup_backup_download

    async def fake_to_thread(*_args, **_kwargs):
        entered.set()
        await release.wait()
        zip_path.write_bytes(b"late result")
        return zip_path, "backup.zip"

    def cleanup(path: Path) -> None:
        real_cleanup(path)
        cleaned.set()

    async def run() -> None:
        monkeypatch.setattr(db_api.asyncio, "to_thread", fake_to_thread)
        monkeypatch.setattr(backup, "cleanup_backup_download", cleanup)
        task = asyncio.create_task(db_api._prepare_backup_download_async("ignored", None))
        await entered.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        release.set()
        await cleaned.wait()

    asyncio.run(run())
    assert not work.exists()
