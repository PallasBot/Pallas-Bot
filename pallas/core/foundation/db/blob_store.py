"""image_cache 二进制落本地文件，DB 只存元数据（历史 bytea 进库拖垮 DELETE/autovacuum）。"""

from __future__ import annotations

import hashlib
import os
import secrets
import stat
from contextlib import suppress
from pathlib import Path
from typing import TYPE_CHECKING

from pallas.core.foundation.paths import DATA_ROOT

if TYPE_CHECKING:
    from collections.abc import Iterator

BLOB_ROOT_NAME = "image_cache_blobs"
_BLOB_ROOT = DATA_ROOT / BLOB_ROOT_NAME


def image_blob_rel_path(content_hash: str) -> Path:
    return Path(BLOB_ROOT_NAME) / content_hash[:2] / f"{content_hash}.img"


def image_blob_abs_path(content_hash: str) -> Path:
    return _BLOB_ROOT / content_hash[:2] / f"{content_hash}.img"


def image_blob_is_regular_file(content_hash: str) -> bool:
    try:
        return stat.S_ISREG(image_blob_abs_path(content_hash).lstat().st_mode)
    except FileNotFoundError:
        return False


def write_image_blob(content_hash: str, data: bytes) -> int:
    """原子写 blob（唯一临时文件 + rename）。返回字节数。"""
    if not content_hash:
        raise ValueError("image blob content_hash is required")
    path = image_blob_abs_path(content_hash)
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        existing_mode = stat.S_IMODE(path.stat().st_mode)
    except FileNotFoundError:
        existing_mode = None
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    for _ in range(100):
        tmp_path = path.with_name(f".{path.name}.{secrets.token_hex(8)}.tmp")
        try:
            fd = os.open(tmp_path, flags, 0o666)
        except FileExistsError:
            continue
        break
    else:
        raise FileExistsError(f"unable to allocate temporary blob file for {path}")
    try:
        with os.fdopen(fd, "wb") as tmp:
            tmp.write(data)
        if existing_mode is not None:
            tmp_path.chmod(existing_mode)
        tmp_path.replace(path)
    finally:
        with suppress(FileNotFoundError):
            tmp_path.unlink()
    return len(data)


def read_image_blob(content_hash: str) -> bytes | None:
    path = image_blob_abs_path(content_hash)
    try:
        if not stat.S_ISREG(path.stat().st_mode):
            return None
        return path.read_bytes()
    except FileNotFoundError:
        return None


def image_blob_size(content_hash: str) -> int:
    path = image_blob_abs_path(content_hash)
    try:
        info = path.stat()
    except FileNotFoundError:
        return 0
    return info.st_size if stat.S_ISREG(info.st_mode) else 0


def delete_image_blob(content_hash: str) -> bool:
    with suppress(FileNotFoundError):
        image_blob_abs_path(content_hash).unlink()
        return True
    return False


def read_image_blob_at(rel_path: str) -> bytes | None:
    """按 DB 相对路径读文件；防止路径穿越只允许 image_cache_blobs 下 .img。"""
    if not rel_path:
        return None
    path = (DATA_ROOT / rel_path).resolve()
    if DATA_ROOT.resolve() not in path.parents or not path.name.endswith(".img"):
        return None
    try:
        if not stat.S_ISREG(path.stat().st_mode):
            return None
        return path.read_bytes()
    except FileNotFoundError:
        return None


def content_hash_from_blob_path(rel_path: str) -> str | None:
    if not rel_path:
        return None
    name = Path(rel_path).name
    if not name.endswith(".img"):
        return None
    return name[: -len(".img")]


def canonical_image_blob_hash(rel_path: str) -> str | None:
    content_hash = content_hash_from_blob_path(rel_path)
    if content_hash and str(image_blob_rel_path(content_hash)) == rel_path:
        return content_hash
    return None


def blob_sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def iter_image_blob_files() -> Iterator[tuple[str, int]]:
    """遍历 data/image_cache_blobs，返回 (content_hash, size)，跳过残留 .tmp。"""
    try:
        for sub in _BLOB_ROOT.iterdir():
            if len(sub.name) != 2:
                continue
            try:
                if not stat.S_ISDIR(sub.stat().st_mode):
                    continue
                for file in sub.iterdir():
                    if not file.name.endswith(".img"):
                        continue
                    try:
                        info = file.stat()
                    except FileNotFoundError:
                        continue
                    if stat.S_ISREG(info.st_mode):
                        yield file.name[: -len(".img")], info.st_size
            except FileNotFoundError:
                continue
    except FileNotFoundError:
        return
