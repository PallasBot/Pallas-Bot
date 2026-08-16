"""image_cache 二进制落本地文件，DB 只存元数据（历史 bytea 进库拖垮 DELETE/autovacuum）。"""

from __future__ import annotations

import hashlib
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


def write_image_blob(content_hash: str, data: bytes) -> int:
    """原子写 blob（临时文件 + rename），同 hash 并发写幂等。返回字节数。"""
    if not content_hash:
        raise ValueError("image blob content_hash is required")
    path = image_blob_abs_path(content_hash)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_bytes(data)
    tmp.replace(path)
    return len(data)


def read_image_blob(content_hash: str) -> bytes | None:
    path = image_blob_abs_path(content_hash)
    if not path.is_file():
        return None
    return path.read_bytes()


def image_blob_size(content_hash: str) -> int:
    path = image_blob_abs_path(content_hash)
    if not path.is_file():
        return 0
    return path.stat().st_size


def delete_image_blob(content_hash: str) -> None:
    with suppress(FileNotFoundError):
        image_blob_abs_path(content_hash).unlink()


def read_image_blob_at(rel_path: str) -> bytes | None:
    """按 DB 相对路径读文件；防止路径穿越只允许 image_cache_blobs 下 .img。"""
    if not rel_path:
        return None
    path = (DATA_ROOT / rel_path).resolve()
    if DATA_ROOT.resolve() not in path.parents or not path.name.endswith(".img") or not path.is_file():
        return None
    return path.read_bytes()


def content_hash_from_blob_path(rel_path: str) -> str | None:
    if not rel_path:
        return None
    name = Path(rel_path).name
    if not name.endswith(".img"):
        return None
    return name[: -len(".img")]


def blob_sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def iter_image_blob_files() -> Iterator[tuple[str, int]]:
    """遍历 data/image_cache_blobs，返回 (content_hash, size)，跳过残留 .tmp。"""
    if not _BLOB_ROOT.is_dir():
        return
    for sub in _BLOB_ROOT.iterdir():
        if not sub.is_dir() or len(sub.name) != 2:
            continue
        for f in sub.iterdir():
            if f.is_file() and f.name.endswith(".img"):
                yield f.name[: -len(".img")], f.stat().st_size
