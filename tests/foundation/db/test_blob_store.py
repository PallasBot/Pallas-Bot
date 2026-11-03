import os
import stat
from pathlib import Path

import pytest

from pallas.core.foundation.db import blob_store


def _isolate_blob_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(blob_store, "DATA_ROOT", tmp_path)
    monkeypatch.setattr(blob_store, "_BLOB_ROOT", tmp_path / blob_store.BLOB_ROOT_NAME)


@pytest.mark.parametrize("reader", ["hash", "path"])
def test_blob_read_treats_unlink_between_stat_and_read_as_missing(tmp_path, monkeypatch, reader):
    _isolate_blob_root(tmp_path, monkeypatch)
    content_hash = "a" * 64
    blob_store.write_image_blob(content_hash, b"image")
    path = blob_store.image_blob_abs_path(content_hash)
    original_read_bytes = Path.read_bytes

    def unlink_before_read(target: Path) -> bytes:
        if target == path:
            target.unlink()
            raise FileNotFoundError(target)
        return original_read_bytes(target)

    monkeypatch.setattr(Path, "read_bytes", unlink_before_read)
    if reader == "hash":
        result = blob_store.read_image_blob(content_hash)
    else:
        result = blob_store.read_image_blob_at(str(blob_store.image_blob_rel_path(content_hash)))
    assert result is None


@pytest.mark.parametrize("reader", ["hash", "path"])
def test_blob_read_propagates_non_missing_file_errors(tmp_path, monkeypatch, reader):
    _isolate_blob_root(tmp_path, monkeypatch)
    content_hash = "b" * 64
    blob_store.write_image_blob(content_hash, b"image")
    path = blob_store.image_blob_abs_path(content_hash)
    original_read_bytes = Path.read_bytes

    def fail_read(target: Path) -> bytes:
        if target == path:
            raise PermissionError(target)
        return original_read_bytes(target)

    monkeypatch.setattr(Path, "read_bytes", fail_read)
    with pytest.raises(PermissionError):
        (
            blob_store.read_image_blob(content_hash)
            if reader == "hash"
            else blob_store.read_image_blob_at(str(blob_store.image_blob_rel_path(content_hash)))
        )


def test_blob_size_treats_unlink_during_stat_as_missing(tmp_path, monkeypatch):
    _isolate_blob_root(tmp_path, monkeypatch)
    content_hash = "c" * 64
    blob_store.write_image_blob(content_hash, b"image")
    path = blob_store.image_blob_abs_path(content_hash)
    original_stat = Path.stat

    def unlink_before_stat(target: Path, *args, **kwargs):
        if target == path:
            target.unlink()
            raise FileNotFoundError(target)
        return original_stat(target, *args, **kwargs)

    monkeypatch.setattr(Path, "stat", unlink_before_stat)
    assert blob_store.image_blob_size(content_hash) == 0


def test_blob_scan_skips_unlink_race_but_propagates_other_errors(tmp_path, monkeypatch):
    _isolate_blob_root(tmp_path, monkeypatch)
    content_hash = "d" * 64
    blob_store.write_image_blob(content_hash, b"image")
    path = blob_store.image_blob_abs_path(content_hash)
    original_stat = Path.stat

    def unlink_before_stat(target: Path, *args, **kwargs):
        if target == path:
            target.unlink()
            raise FileNotFoundError(target)
        return original_stat(target, *args, **kwargs)

    monkeypatch.setattr(Path, "stat", unlink_before_stat)
    assert list(blob_store.iter_image_blob_files()) == []

    monkeypatch.setattr(Path, "stat", original_stat)
    blob_store.write_image_blob(content_hash, b"image")

    def fail_stat(target: Path, *args, **kwargs):
        if target == path:
            raise PermissionError(target)
        return original_stat(target, *args, **kwargs)

    monkeypatch.setattr(Path, "stat", fail_stat)
    with pytest.raises(PermissionError):
        list(blob_store.iter_image_blob_files())


def test_blob_write_preserves_umask_and_existing_mode(tmp_path, monkeypatch):
    _isolate_blob_root(tmp_path, monkeypatch)
    content_hash = "e" * 64
    old_umask = os.umask(0o027)
    try:
        blob_store.write_image_blob(content_hash, b"first")
    finally:
        os.umask(old_umask)
    path = blob_store.image_blob_abs_path(content_hash)
    assert stat.S_IMODE(path.stat().st_mode) == 0o640

    path.chmod(0o604)
    blob_store.write_image_blob(content_hash, b"second")
    assert stat.S_IMODE(path.stat().st_mode) == 0o604


def test_blob_regular_file_check_does_not_follow_symlink(tmp_path, monkeypatch):
    _isolate_blob_root(tmp_path, monkeypatch)
    link_hash = "f" * 64
    target_hash = "e" * 64
    content = b"target bytes"
    blob_store.write_image_blob(target_hash, content)
    link = blob_store.image_blob_abs_path(link_hash)
    link.parent.mkdir(parents=True)
    link.symlink_to(blob_store.image_blob_abs_path(target_hash))
    directory_hash = "d" * 64
    directory = blob_store.image_blob_abs_path(directory_hash)
    directory.mkdir(parents=True)

    assert blob_store.image_blob_is_regular_file(target_hash)
    assert not blob_store.image_blob_is_regular_file(link_hash)
    assert not blob_store.image_blob_is_regular_file(directory_hash)
    assert not blob_store.image_blob_is_regular_file("a" * 64)
