# Derived from the PRTS corpus engine, Copyright (c) 2026 Pallas contributors.
# Modified 2026-10-26; distributed under the MIT License (see PRTS-LICENSE).

from __future__ import annotations

import base64
import functools
import gzip
import hashlib
import json
import os
import re
import shutil
import stat
import tempfile
import threading
import unicodedata
import urllib.error
import urllib.request
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any
from urllib.parse import urlsplit

from pallas.core.foundation.fs_lock import interprocess_file_lock

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable

CURRENT_URL = "https://prts.chat/api/agent/data/releases/current"
SITE_BASE_URL = "https://prts.chat/api/agent/data/releases"
MODEL_SCOPE_PACK_REPOS = {
    "official_game": "HTiantian/prts-agent-corpus-arknights",
    "reviewed_wiki": "HTiantian/prts-agent-corpus-arknights",
    "terra_journey": "HTiantian/prts-agent-corpus-arknights",
    "entities": "HTiantian/prts-agent-corpus-arknights",
    "references": "HTiantian/prts-agent-corpus-arknights",
    "endfield_official_game": "HTiantian/prts-agent-corpus-endfield",
    "endfield_reviewed_knowledge": "HTiantian/prts-agent-corpus-endfield",
}
ALLOWED_PACKS = frozenset(MODEL_SCOPE_PACK_REPOS)
MAX_MATCH_CHARS = 1600
MAX_METADATA_BYTES = 4 * 1024 * 1024
MAX_ASSET_FILES = 20_000
MAX_ASSET_COMPRESSED_BYTES = 1024 * 1024 * 1024
MAX_GENERATION_COMPRESSED_BYTES = 8 * 1024 * 1024 * 1024
MAX_GZIP_UNCOMPRESSED_BYTES = 256 * 1024 * 1024
MAX_GENERATION_UNCOMPRESSED_BYTES = 16 * 1024 * 1024 * 1024
MAX_QUERY_GZIP_UNCOMPRESSED_BYTES = 512 * 1024 * 1024
MAX_STORE_CACHE_BYTES = 1024 * 1024 * 1024
MAX_GZIP_LINE_BYTES = 16 * 1024 * 1024
_ALLOWED_UPSTREAM_HOSTS = frozenset({"prts.chat", "modelscope.cn"})
_CURRENT_POINTER = object()


class CorpusError(RuntimeError):
    pass


class CorpusNotFoundError(CorpusError):
    pass


class CorpusUnavailableError(CorpusError):
    pass


@dataclass(frozen=True)
class DocumentLocation:
    pack_id: str
    document_id: str
    shard_path: str
    record_index: int
    summary: dict[str, Any]
    search_index_id: int | None


def corpus_root(data_dir: Path) -> Path:
    return data_dir / "releases"


def parse_pack_ids(raw: str, *, include_endfield: bool = False) -> list[str]:
    packs = [item.strip() for item in str(raw or "").split(",") if item.strip()]
    if include_endfield:
        packs.extend(("endfield_official_game", "endfield_reviewed_knowledge"))
    return list(dict.fromkeys(item for item in packs if item in ALLOWED_PACKS))


def _validate_upstream_url(url: str) -> None:
    parsed = urlsplit(url)
    if (
        parsed.scheme != "https"
        or parsed.hostname not in _ALLOWED_UPSTREAM_HOSTS
        or parsed.username
        or parsed.password
        or parsed.port not in (None, 443)
        or parsed.query
        or parsed.fragment
    ):
        raise CorpusError("PRTS 上游地址不在固定白名单内")


class _SafeRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        _validate_upstream_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _open_url(request: urllib.request.Request, *, timeout: int):
    _validate_upstream_url(request.full_url)
    return urllib.request.build_opener(_SafeRedirectHandler()).open(request, timeout=timeout)


def _request_json(url: str, *, timeout: int) -> dict[str, Any]:
    request = urllib.request.Request(url, headers={"Accept": "application/json", "User-Agent": "pallas-prts/0.1"})
    try:
        with _open_url(request, timeout=timeout) as response:
            raw = response.read(MAX_METADATA_BYTES + 1)
        if len(raw) > MAX_METADATA_BYTES:
            raise CorpusError("PRTS 元数据超过大小上限")
        data = json.loads(raw.decode("utf-8"))
    except Exception as exc:
        raise CorpusError(f"读取 PRTS 元数据失败：{exc}") from exc
    if not isinstance(data, dict):
        raise CorpusError("PRTS 元数据不是 JSON 对象")
    return data


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    _assert_no_symlinks(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(payload, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
        Path(temporary).replace(path)
    finally:
        temporary_path = Path(temporary)
        if temporary_path.exists():
            temporary_path.unlink()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _download_verified(urls: Iterable[str], destination: Path, *, size: int, sha256: str, timeout: int) -> None:
    if type(size) is not int or size < 1 or size > MAX_ASSET_COMPRESSED_BYTES:
        raise CorpusError("PRTS 资源压缩大小无效")
    if not re.fullmatch(r"[0-9a-fA-F]{64}", sha256):
        raise CorpusError("PRTS 资源 SHA-256 格式无效")
    _assert_no_symlinks(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.is_file() and destination.stat().st_size == size and _sha256_file(destination) == sha256:
        return
    last_error: Exception | None = None
    for url in urls:
        temporary = None
        try:
            request = urllib.request.Request(url, headers={"User-Agent": "pallas-prts/0.1"})
            with _open_url(request, timeout=timeout) as response:
                fd, temporary = tempfile.mkstemp(prefix=f".{destination.name}.", suffix=".part", dir=destination.parent)
                with os.fdopen(fd, "wb") as stream:
                    total = 0
                    while block := response.read(1024 * 1024):
                        total += len(block)
                        if total > size:
                            raise CorpusError("PRTS 下载文件超过声明大小")
                        stream.write(block)
            temporary_path = Path(temporary)
            if temporary_path.stat().st_size != size or _sha256_file(temporary_path) != sha256:
                raise CorpusError(f"文件校验失败：{url}")
            temporary_path.replace(destination)
            return
        except (CorpusError, OSError, urllib.error.URLError) as exc:
            last_error = exc
            temporary_path = Path(temporary) if temporary else None
            if temporary_path is not None and temporary_path.exists():
                temporary_path.unlink()
    raise CorpusError(f"下载语料失败：{last_error}")


def _asset_rows(pack: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    catalog = pack.get("document_catalog")
    if isinstance(catalog, dict):
        rows.append(catalog)
    shards = pack.get("shards")
    if isinstance(shards, list):
        rows.extend(item for item in shards if isinstance(item, dict))
    search = pack.get("search_index")
    if isinstance(search, dict):
        index_shards = search.get("shards")
        if isinstance(index_shards, list):
            rows.extend(item for item in index_shards if isinstance(item, dict))
    return rows


def _pack_assets_present(
    snapshot_path: Path,
    pack_id: str,
    manifest: dict[str, Any],
    *,
    require_search_index: bool,
) -> bool:
    catalog = manifest.get("document_catalog")
    shards = manifest.get("shards", [])
    if (
        not isinstance(catalog, dict)
        or not isinstance(shards, list)
        or any(not isinstance(row, dict) for row in shards)
    ):
        return False
    assets = [catalog, *shards]
    search = manifest.get("search_index")
    if require_search_index and search is not None:
        if not isinstance(search, dict):
            return False
        index_shards = search.get("shards", [])
        if not isinstance(index_shards, list) or any(not isinstance(row, dict) for row in index_shards):
            return False
        assets.extend(index_shards)
    for asset in assets:
        path = asset.get("path")
        if type(path) is not str or not path:
            return False
        try:
            asset_path = _safe_asset_path(snapshot_path / pack_id, path)
        except CorpusError:
            return False
        if not asset_path.is_file():
            return False
    return True


def _safe_asset_path(base: Path, raw_path: str) -> Path:
    if type(raw_path) is not str:
        raise CorpusError("PRTS 资源路径无效")
    path = raw_path
    if not path or "\\" in path or "\0" in path:
        raise CorpusError("PRTS 资源路径无效")
    relative = Path(path)
    if relative.is_absolute() or ".." in relative.parts:
        raise CorpusError("PRTS 资源路径越界")
    candidate = base.joinpath(*relative.parts)
    _assert_no_symlinks(candidate)
    try:
        candidate.resolve(strict=False).relative_to(base.resolve(strict=False))
    except (OSError, ValueError) as exc:
        raise CorpusError("PRTS 资源路径越界") from exc
    return candidate


def _assert_no_symlinks(path: Path) -> None:
    current = Path(path.anchor)
    for part in path.parts[1:]:
        current /= part
        try:
            mode = current.lstat().st_mode
        except FileNotFoundError:
            continue
        except OSError as exc:
            raise CorpusError("PRTS 本地路径无法检查") from exc
        if stat.S_ISLNK(mode):
            raise CorpusError("PRTS 本地路径包含符号链接")


def _safe_release_dir(data_dir: Path, release_id: str) -> Path:
    if type(release_id) is not str:
        raise CorpusError("PRTS release_id 非法")
    raw = release_id
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}", raw) or raw in {".", ".."}:
        raise CorpusError("PRTS release_id 非法")
    return _safe_asset_path(corpus_root(data_dir), raw)


def _snapshot_dir(data_dir: Path, pointer: dict[str, Any]) -> Path:
    _safe_release_dir(data_dir, pointer.get("release_id"))
    generation = pointer.get("generation") or ""
    if type(generation) is not str:
        raise CorpusError("PRTS generation 指针非法")
    if generation:
        if not generation.startswith("generations/"):
            raise CorpusError("PRTS generation 指针非法")
        return _safe_asset_path(corpus_root(data_dir), generation)
    return _safe_release_dir(data_dir, pointer.get("release_id"))


def _read_gzip_bytes(path: Path, *, limit: int | None = None, account=None) -> bytes:
    limit = MAX_GZIP_UNCOMPRESSED_BYTES if limit is None else limit
    try:
        with gzip.open(path, "rb") as stream:
            parts = []
            total = 0
            while block := stream.read(min(1024 * 1024, limit - total + 1)):
                total += len(block)
                if total > limit:
                    raise CorpusError("PRTS gzip 解压超过大小上限")
                if account is not None:
                    account(len(block))
                parts.append(block)
    except FileNotFoundError as exc:
        raise CorpusUnavailableError(f"PRTS gzip 资源缺失：{path}") from exc
    except (OSError, EOFError) as exc:
        raise CorpusError("PRTS gzip 资源损坏") from exc
    return b"".join(parts)


def _iter_gzip_lines(path: Path, *, limit: int | None = None, account=None):
    limit = MAX_GZIP_UNCOMPRESSED_BYTES if limit is None else limit
    total = 0
    try:
        with gzip.open(path, "rb") as stream:
            while True:
                raw = stream.readline(min(MAX_GZIP_LINE_BYTES, limit - total + 1))
                if not raw:
                    return
                total += len(raw)
                if total > limit:
                    raise CorpusError("PRTS gzip 解压超过大小上限")
                if len(raw) == MAX_GZIP_LINE_BYTES and not raw.endswith(b"\n"):
                    raise CorpusError("PRTS gzip JSONL 行超过大小上限")
                if account is not None:
                    account(len(raw))
                yield raw.decode("utf-8")
    except FileNotFoundError as exc:
        raise CorpusUnavailableError(f"PRTS gzip 资源缺失：{path}") from exc
    except (OSError, EOFError, UnicodeDecodeError) as exc:
        raise CorpusError("PRTS gzip 资源损坏") from exc


def _validate_gzip_asset(path: Path, total_uncompressed: int) -> int:
    try:
        with path.open("rb") as stream:
            magic = stream.read(2)
    except OSError as exc:
        raise CorpusError("PRTS 下载文件无法读取") from exc
    if magic != b"\x1f\x8b":
        return total_uncompressed
    size = 0
    try:
        with gzip.open(path, "rb") as stream:
            while block := stream.read(1024 * 1024):
                size += len(block)
                if size > MAX_GZIP_UNCOMPRESSED_BYTES:
                    raise CorpusError("PRTS gzip 解压超过单文件上限")
                if total_uncompressed + size > MAX_GENERATION_UNCOMPRESSED_BYTES:
                    raise CorpusError("PRTS 语料累计解压超过大小上限")
    except (OSError, EOFError) as exc:
        raise CorpusError("PRTS gzip 资源损坏") from exc
    return total_uncompressed + size


def _mirror_urls(current: dict[str, Any], pack_id: str, release_id: str, path: str) -> list[str]:
    urls: list[str] = []
    mirrors = current.get("mirrors")
    for mirror in mirrors if isinstance(mirrors, list) else []:
        if not isinstance(mirror, dict) or pack_id not in (mirror.get("pack_ids") or []):
            continue
        base = str(mirror.get("base_url") or "").rstrip("/")
        try:
            _validate_upstream_url(base)
        except (CorpusError, ValueError):
            continue
        if base:
            urls.append(f"{base}/{pack_id}/{path}")
    repo = MODEL_SCOPE_PACK_REPOS.get(pack_id)
    if repo:
        urls.append(f"https://modelscope.cn/datasets/{repo}/resolve/master/releases/{release_id}/{pack_id}/{path}")
    urls.append(f"{SITE_BASE_URL}/{release_id}/{pack_id}/{path}")
    return list(dict.fromkeys(urls))


def sync_packs(
    data_dir: Path,
    pack_ids: list[str],
    *,
    timeout: int = 120,
    current_payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    requested = [pack_id for pack_id in pack_ids if pack_id in ALLOWED_PACKS]
    if not requested:
        raise CorpusError("没有选择有效的 PRTS pack")
    if current_payload is None:
        current_payload = _request_json(CURRENT_URL, timeout=timeout)
    data = current_payload.get("data")
    if current_payload.get("code") != 200 or not isinstance(data, dict):
        raise CorpusError("PRTS current 响应无效")
    release_id = data.get("release_id")
    data_version = data.get("data_version")
    if (
        type(release_id) is not str
        or type(data_version) is not str
        or not re.fullmatch(r"[0-9a-fA-F]{64}", data_version)
    ):
        raise CorpusError("PRTS current 缺少 release_id 或 data_version")
    _safe_release_dir(data_dir, release_id)
    release_manifest = _request_json(
        f"{SITE_BASE_URL}/{release_id}/release-manifest.json",
        timeout=timeout,
    )
    if release_manifest.get("release_id") != release_id or release_manifest.get("data_version") != data_version:
        raise CorpusError("PRTS release-manifest 与 current 不一致")
    license_rows = release_manifest.get("licenses")
    if not isinstance(license_rows, list) or any(not isinstance(item, dict) for item in license_rows):
        raise CorpusError("PRTS release-manifest license 信息无效")
    licenses = {}
    for item in license_rows:
        pack_id = item.get("pack_id")
        if type(pack_id) is not str or not pack_id or pack_id in licenses:
            raise CorpusError("PRTS release-manifest license 标识重复或无效")
        licenses[pack_id] = item
    pack_rows = release_manifest.get("packs")
    if not isinstance(pack_rows, list) or len(pack_rows) > MAX_ASSET_FILES:
        raise CorpusError("PRTS release-manifest pack 数量无效")
    descriptor_by_id = {str(item.get("pack_id")): item for item in pack_rows if isinstance(item, dict)}
    if len(descriptor_by_id) != len(pack_rows):
        raise CorpusError("PRTS release-manifest pack 标识重复或无效")

    root = corpus_root(data_dir)
    generations = root / "generations"
    _assert_no_symlinks(generations)
    generations.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=".staging-", dir=generations))
    total_compressed = 0
    total_uncompressed = 0
    asset_count = 0
    try:
        for pack_id in requested:
            descriptor = descriptor_by_id.get(pack_id)
            if descriptor is None:
                raise CorpusError(f"当前 release 不包含 pack：{pack_id}")
            license_row = licenses.get(pack_id)
            if license_row is None or license_row.get("public_distribution_approved") is not True:
                raise CorpusError(f"当前 release 未批准公开下载 pack：{pack_id}")
            manifest_path = descriptor.get("manifest_path") or f"{pack_id}/pack-manifest.json"
            if type(manifest_path) is not str:
                raise CorpusError("PRTS pack-manifest 路径无效")
            safe_manifest = _safe_asset_path(root, manifest_path)
            relative_manifest = "/".join(safe_manifest.relative_to(root).parts)
            pack_manifest = _request_json(f"{SITE_BASE_URL}/{release_id}/{relative_manifest}", timeout=timeout)
            if pack_manifest.get("pack_id") not in (None, pack_id):
                raise CorpusError(f"pack-manifest 标识错误：{pack_id}")
            rows = _asset_rows(pack_manifest)
            if not rows or asset_count + len(rows) > MAX_ASSET_FILES:
                raise CorpusError("PRTS 资源文件数量无效或超过上限")
            pack_dir = staging / pack_id
            _write_json(pack_dir / "pack-manifest.json", pack_manifest)
            paths: set[str] = set()
            for asset in rows:
                path = asset.get("path")
                size = asset.get("compressed_size")
                sha256 = asset.get("sha256")
                if (
                    type(path) is not str
                    or not path
                    or len(path) > 512
                    or path in paths
                    or type(size) is not int
                    or size < 1
                    or size > MAX_ASSET_COMPRESSED_BYTES
                    or type(sha256) is not str
                    or not re.fullmatch(r"[0-9a-fA-F]{64}", sha256)
                ):
                    raise CorpusError(f"pack-manifest 资源描述错误：{pack_id}")
                paths.add(path)
                total_compressed += size
                if total_compressed > MAX_GENERATION_COMPRESSED_BYTES:
                    raise CorpusError("PRTS 语料累计压缩大小超过上限")
                asset_path = _safe_asset_path(pack_dir, path)
                _download_verified(
                    _mirror_urls(data, pack_id, release_id, path),
                    asset_path,
                    size=size,
                    sha256=sha256,
                    timeout=timeout,
                )
                total_uncompressed = _validate_gzip_asset(asset_path, total_uncompressed)
                asset_count += 1

        generation_id = f"generations/{release_id}-{data_version[:12]}-{uuid.uuid4().hex}"
        destination = _safe_asset_path(root, generation_id)
        staging.replace(destination)
        pointer = {
            "release_id": release_id,
            "data_version": data_version,
            "generation": generation_id,
            "packs": requested,
            "document_count": release_manifest.get("document_count"),
            "synced_at": datetime.now(UTC).isoformat(),
        }
        _write_json(root / "current.json", pointer)
        return pointer
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise


_SYNC_LOCK = threading.Lock()


@contextmanager
def _update_lock(data_dir: Path):
    root = corpus_root(data_dir)
    _assert_no_symlinks(root / ".update.lock")
    root.mkdir(parents=True, exist_ok=True)
    with _SYNC_LOCK:
        with interprocess_file_lock(root / ".update.lock"):
            yield


def sync_packs_locked(data_dir: Path, pack_ids: list[str], *, timeout: int = 120) -> dict[str, Any]:
    """手动同步入口；锁在下载线程内持有，异步取消不会提前释放。"""
    with _update_lock(data_dir):
        return sync_packs(data_dir, pack_ids, timeout=timeout)


def _read_pointer_file(data_dir: Path) -> dict[str, Any] | None:
    path = corpus_root(data_dir) / "current.json"
    _assert_no_symlinks(path)
    if not path.is_file():
        return None
    try:
        if path.stat().st_size > MAX_METADATA_BYTES:
            raise CorpusError("PRTS current 指针超过大小上限")
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    if (
        type(data.get("data_version")) is not str
        or not re.fullmatch(r"[0-9a-fA-F]{64}", data["data_version"])
        or not isinstance(data.get("packs"), list)
        or len(data["packs"]) > len(ALLOWED_PACKS)
        or any(type(pack) is not str or pack not in ALLOWED_PACKS for pack in data["packs"])
    ):
        raise CorpusError("PRTS current 指针内容无效")
    _snapshot_dir(data_dir, data)
    return data


def _release_files_present(data_dir: Path, release_id: str, pack_ids: Iterable[str]) -> bool:
    pointer = _read_pointer_file(data_dir) or {}
    release_dir = (
        _snapshot_dir(data_dir, pointer)
        if pointer.get("release_id") == release_id
        else _safe_release_dir(data_dir, release_id)
    )
    for pack_id in pack_ids:
        manifest_path = release_dir / pack_id / "pack-manifest.json"
        _assert_no_symlinks(manifest_path)
        if not manifest_path.is_file():
            return False
        try:
            if manifest_path.stat().st_size > MAX_METADATA_BYTES:
                return False
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return False
        if not isinstance(manifest, dict):
            return False
        for asset in _asset_rows(manifest):
            path = asset.get("path")
            if type(path) is not str or not path or len(path) > 512:
                return False
            asset_path = _safe_asset_path(release_dir / pack_id, path)
            if not asset_path.is_file():
                return False
            size = asset.get("compressed_size")
            if type(size) is not int or size < 1 or size > MAX_ASSET_COMPRESSED_BYTES:
                return False
            if asset_path.stat().st_size != size:
                return False
    return True


def auto_update_pack_scope(data_dir: Path, configured: Iterable[str]) -> list[str]:
    pointer = _read_pointer_file(data_dir) or {}
    installed = [str(pack) for pack in pointer.get("packs") or [] if pack in ALLOWED_PACKS]
    ordered = [pack for pack in configured if pack in ALLOWED_PACKS] + installed
    return list(dict.fromkeys(ordered))


def auto_update_if_needed(data_dir: Path, pack_ids: list[str], *, timeout: int = 120) -> dict[str, Any]:
    """按需检查并下载；不得在启动或查询时触发。"""
    with _update_lock(data_dir):
        return _auto_update_if_needed(data_dir, pack_ids, timeout=timeout)


def _auto_update_if_needed(data_dir: Path, pack_ids: list[str], *, timeout: int) -> dict[str, Any]:
    desired = auto_update_pack_scope(data_dir, pack_ids)
    if not desired:
        raise CorpusError("没有选择有效的 PRTS pack")
    current_payload = _request_json(CURRENT_URL, timeout=timeout)
    data = current_payload.get("data")
    if current_payload.get("code") != 200 or not isinstance(data, dict):
        raise CorpusError("PRTS current 响应无效")
    release_id = data.get("release_id")
    data_version = data.get("data_version")
    if (
        type(release_id) is not str
        or type(data_version) is not str
        or not re.fullmatch(r"[0-9a-fA-F]{64}", data_version)
    ):
        raise CorpusError("PRTS current 缺少 release_id 或 data_version")
    _safe_release_dir(data_dir, release_id)
    local = _read_pointer_file(data_dir) or {}
    local_release = str(local.get("release_id") or "")
    local_version = str(local.get("data_version") or "")
    same_release = local_release == release_id and local_version == data_version
    local_packs = {str(pack) for pack in local.get("packs") or []}
    if (
        same_release
        and all(pack in local_packs for pack in desired)
        and _release_files_present(data_dir, release_id, desired)
    ):
        return {
            "updated": False,
            "release_id": release_id,
            "data_version": data_version,
            "packs": desired,
        }
    pointer = sync_packs(data_dir, desired, timeout=timeout, current_payload=current_payload)
    return {"updated": True, **pointer}


def _normalize(value: Any) -> str:
    return " ".join(unicodedata.normalize("NFKC", str(value or "")).split()).lower()


def _ngrams(value: str) -> list[str]:
    chars = list(_normalize(value))
    if not chars:
        return []
    size = min(3, len(chars))
    return list(dict.fromkeys("".join(chars[index : index + size]) for index in range(len(chars) - size + 1)))


def _document_uid(document_id: str) -> str:
    digest = hashlib.sha256(f"prts-document\0{document_id}".encode()).digest()[:12]
    return f"doc_{base64.urlsafe_b64encode(digest).decode().rstrip('=')}"


def _game(summary: dict[str, Any]) -> str:
    explicit = _normalize(summary.get("game"))
    if explicit in {"arknights", "endfield"}:
        return explicit
    identity = f"{summary.get('document_id', '')} {summary.get('source_ref_prefix', '')}".lower()
    return "endfield" if "endfield:" in identity else "arknights"


def _resource_type(summary: dict[str, Any]) -> str:
    explicit = str(summary.get("resource_type") or "").strip()
    if explicit:
        return explicit
    kind = str(summary.get("document_kind") or "")
    document_type = str(summary.get("document_type") or "")
    category = str(summary.get("document_category") or "")
    if document_type == "story":
        return "operator_record" if category == "memory" else "story"
    if document_type == "character":
        return "character_module" if category == "模组文案" else "character_profile"
    if document_type == "entity":
        return "entity_profile"
    if document_type == "reference":
        return "timeline" if kind == "reference" else "reference"
    return "knowledge"


def _line_text(line: dict[str, Any]) -> str:
    speaker = str(line.get("speaker_raw") or "").strip()
    text = str(line.get("text") or "")
    return f"{speaker}: {text}" if speaker else text


def _serialized(method: Callable) -> Callable:
    """以 search/read 实例锁串行化入口，避免并发线程混用 release 缓存与指针。"""

    @functools.wraps(method)
    def wrapper(self, *args, **kwargs):
        with self._lock:
            self._query_decompressed_bytes = 0
            return method(self, *args, **kwargs)

    return wrapper


def _names_serialized(method: Callable) -> Callable:
    """实体目录入口使用独立实例锁，不与 search/read 锁互相阻塞。"""

    @functools.wraps(method)
    def wrapper(self, *args, **kwargs):
        with self._names_lock:
            self._names_decompressed_bytes = 0
            return method(self, *args, **kwargs)

    return wrapper


class CorpusStore:
    def __init__(self, data_dir: Path):
        self.data_dir = data_dir
        self.root = corpus_root(data_dir)
        self._lock = threading.RLock()
        self._names_lock = threading.RLock()
        self._loaded_key = ""
        self._release_id = ""
        self._data_version = ""
        self._snapshot_path: Path | None = None
        self._cache_bytes = 0
        self._query_decompressed_bytes = 0
        self._names_decompressed_bytes = 0
        self._locations: dict[tuple[str, str], DocumentLocation] = {}
        self._by_id: dict[str, DocumentLocation] = {}
        self._by_uid: dict[str, DocumentLocation] = {}
        self._by_title: dict[str, list[DocumentLocation]] = {}
        self._shard_cache: dict[tuple[str, str], list[dict[str, Any]]] = {}
        self._index_cache: dict[tuple[str, str], dict[str, list[int]]] = {}
        self._manifests: dict[str, dict[str, Any]] = {}
        self._entity_names_key = ""
        self._entity_names_cache: tuple[str, ...] = ()

    def snapshot(self) -> dict[str, Any] | None:
        """Capture one validated current pointer for a multi-step query."""
        return self._read_pointer()

    def status(
        self,
        *,
        pointer: Any = _CURRENT_POINTER,
        pack_ids: Iterable[str] | None = None,
        require_search_index: bool = False,
    ) -> dict[str, Any]:
        if pointer is _CURRENT_POINTER:
            pointer = self._read_pointer()
        if not pointer:
            return {"installed": False, "packs": [], "release_id": "", "data_version": ""}
        snapshot_path = _snapshot_dir(self.data_dir, pointer)
        installed = []
        pointer_packs = pointer.get("packs", [])
        selected = pointer_packs if pack_ids is None else pack_ids
        for pack_id in dict.fromkeys(selected):
            if pack_id not in pointer_packs or pack_id not in ALLOWED_PACKS:
                continue
            try:
                manifest = self._read_manifest(pack_id, pointer.get("release_id"), snapshot_path)
                if manifest and _pack_assets_present(
                    snapshot_path,
                    pack_id,
                    manifest,
                    require_search_index=require_search_index,
                ):
                    try:
                        documents = int(manifest.get("document_count") or 0)
                        lines = int(manifest.get("line_count") or 0)
                    except (TypeError, ValueError):
                        continue
                    installed.append({
                        "pack_id": pack_id,
                        "documents": documents,
                        "lines": lines,
                    })
            except CorpusError:
                continue
        return {
            "installed": bool(installed),
            "release_id": str(pointer.get("release_id") or ""),
            "data_version": str(pointer.get("data_version") or ""),
            "packs": installed,
        }

    def _read_pointer(self) -> dict[str, Any] | None:
        return _read_pointer_file(self.data_dir)

    def _read_manifest(
        self,
        pack_id: str,
        release_id: Any,
        snapshot_path: Path | None = None,
    ) -> dict[str, Any] | None:
        if not release_id:
            return None
        if pack_id not in ALLOWED_PACKS:
            raise CorpusError("PRTS pack 标识无效")
        base = snapshot_path or _snapshot_dir(self.data_dir, self._read_pointer() or {})
        path = _safe_asset_path(base, f"{pack_id}/pack-manifest.json")
        if not path.is_file():
            return None
        try:
            if path.stat().st_size > MAX_METADATA_BYTES:
                raise CorpusError("PRTS pack 清单超过大小上限")
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise CorpusError(f"PRTS pack 清单损坏：{pack_id}: {exc}") from exc
        return data if isinstance(data, dict) else None

    @_names_serialized
    def entity_names(self, *, pack_ids: Iterable[str] = ("entities",)) -> tuple[str, ...]:
        pointer = self._read_pointer()
        if not pointer or not pointer.get("release_id"):
            return ()
        release_id = str(pointer["release_id"])
        data_version = str(pointer.get("data_version") or "")
        snapshot_path = _snapshot_dir(self.data_dir, pointer)
        selected = tuple(pack_id for pack_id in pack_ids if pack_id in pointer.get("packs", []))
        key = f"{pointer.get('generation', release_id)}:{data_version}:{','.join(selected)}"
        if key == self._entity_names_key:
            return self._entity_names_cache
        names: set[str] = set()
        for pack_id in selected:
            manifest = self._read_manifest(pack_id, release_id, snapshot_path)
            catalog = manifest.get("document_catalog") if isinstance(manifest, dict) else None
            if not isinstance(catalog, dict):
                continue
            catalog_path = _safe_asset_path(snapshot_path / pack_id, str(catalog.get("path") or ""))
            if not catalog_path.is_file():
                continue
            try:
                for raw in _iter_gzip_lines(catalog_path):
                    row = json.loads(raw)
                    summary = row.get("document") if isinstance(row, dict) else None
                    if not isinstance(summary, dict):
                        continue
                    for field_name in (
                        "display_title",
                        "character_name",
                        "activity_name",
                        "story_name",
                        "collection_name",
                    ):
                        name = _normalize(summary.get(field_name))
                        if len(name) >= 2:
                            names.add(name)
            except (OSError, json.JSONDecodeError) as exc:
                raise CorpusError(f"读取 PRTS 实体目录失败：{catalog_path}: {exc}") from exc
        self._entity_names_key = key
        self._entity_names_cache = tuple(sorted(names, key=lambda item: (-len(item), item)))
        return self._entity_names_cache

    def contains_entity(self, text: str, *, pack_ids: Iterable[str] = ("entities",)) -> bool:
        query = _normalize(text)
        if not query:
            return False
        for name in self.entity_names(pack_ids=pack_ids):
            if name.isascii() and re.fullmatch(r"[a-z0-9][a-z0-9 ._-]*", name):
                if re.search(rf"(?<![a-z0-9]){re.escape(name)}(?![a-z0-9])", query):
                    return True
            elif name in query:
                return True
        return False

    def _load(
        self,
        pointer: Any = _CURRENT_POINTER,
        pack_ids: Iterable[str] | None = None,
        *,
        require_search_index: bool = False,
    ) -> None:
        if pointer is _CURRENT_POINTER:
            pointer = self._read_pointer()
        if not pointer or not pointer.get("release_id"):
            raise CorpusError("PRTS 语料尚未安装，请先发送 PRTS更新")
        release_id = str(pointer["release_id"])
        data_version = str(pointer.get("data_version") or "")
        snapshot_path = _snapshot_dir(self.data_dir, pointer)
        pointer_packs = pointer.get("packs") or []
        selected_packs = list(
            dict.fromkeys(
                pack_id
                for pack_id in (pointer_packs if pack_ids is None else pack_ids)
                if pack_id in pointer_packs and pack_id in ALLOWED_PACKS
            )
        )
        key_parts = (
            str(pointer.get("generation", release_id)),
            data_version,
            ",".join(selected_packs),
            str(require_search_index),
        )
        key = ":".join(key_parts)
        if key == self._loaded_key:
            return
        self._loaded_key = ""
        self._locations.clear()
        self._by_id.clear()
        self._by_uid.clear()
        self._by_title.clear()
        self._shard_cache.clear()
        self._index_cache.clear()
        self._manifests.clear()
        self._cache_bytes = 0
        self._release_id = release_id
        self._data_version = data_version
        self._snapshot_path = snapshot_path
        for pack_id in selected_packs:
            manifest = self._read_manifest(pack_id, release_id, snapshot_path)
            if not manifest:
                raise CorpusUnavailableError(f"PRTS pack 清单缺失：{pack_id}")
            if not _pack_assets_present(
                snapshot_path,
                pack_id,
                manifest,
                require_search_index=require_search_index,
            ):
                raise CorpusUnavailableError(f"PRTS pack 资源缺失：{pack_id}")
            self._manifests[pack_id] = manifest
            catalog = manifest.get("document_catalog")
            if not isinstance(catalog, dict):
                raise CorpusUnavailableError(f"PRTS pack 目录缺失：{pack_id}")
            catalog_path = _safe_asset_path(snapshot_path / pack_id, str(catalog.get("path") or ""))
            if not catalog_path.is_file():
                raise CorpusUnavailableError(f"PRTS pack 目录缺失：{pack_id}")
            loaded_shards: set[str] = set()
            for raw in _iter_gzip_lines(catalog_path, account=self._account_query_decompressed):
                if not raw.strip():
                    continue
                self._cache_bytes += len(raw.encode("utf-8"))
                if self._cache_bytes > MAX_STORE_CACHE_BYTES:
                    raise CorpusError("PRTS 查询缓存超过大小上限")
                row = json.loads(raw)
                summary = row.get("document") if isinstance(row, dict) else None
                if not isinstance(summary, dict):
                    continue
                document_id = str(summary.get("document_id") or "")
                shard_path = str(row.get("shard_path") or "")
                record_index = row.get("record_index")
                if not document_id or type(record_index) is not int or record_index < 0:
                    continue
                if not shard_path:
                    raise CorpusUnavailableError(f"PRTS pack 分片路径缺失：{pack_id}")
                if shard_path not in loaded_shards:
                    shard_file = _safe_asset_path(snapshot_path / pack_id, shard_path)
                    if not shard_file.is_file():
                        raise CorpusUnavailableError(f"PRTS pack 分片缺失：{pack_id}")
                    loaded_shards.add(shard_path)
                location = DocumentLocation(
                    pack_id=pack_id,
                    document_id=document_id,
                    shard_path=shard_path,
                    record_index=record_index,
                    summary=summary,
                    search_index_id=int(row["search_index_id"]) if row.get("search_index_id") is not None else None,
                )
                self._locations[(pack_id, document_id)] = location
                self._by_id[document_id] = location
                self._by_uid[_document_uid(document_id)] = location
                title = _normalize(summary.get("display_title"))
                if title:
                    self._by_title.setdefault(title, []).append(location)
        self._loaded_key = key

    def _account_query_decompressed(self, size: int) -> None:
        self._query_decompressed_bytes += size
        if self._query_decompressed_bytes > MAX_QUERY_GZIP_UNCOMPRESSED_BYTES:
            raise CorpusError("PRTS 单次查询累计解压超过大小上限")

    def _account_names_decompressed(self, size: int) -> None:
        self._names_decompressed_bytes += size
        if self._names_decompressed_bytes > MAX_QUERY_GZIP_UNCOMPRESSED_BYTES:
            raise CorpusError("PRTS 实体目录累计解压超过大小上限")

    def _release_dir(self, pack_id: str) -> Path:
        if pack_id not in self._manifests or self._snapshot_path is None:
            raise CorpusError("PRTS pack 未安装")
        return self._snapshot_path / pack_id

    def _load_shard(self, location: DocumentLocation) -> list[dict[str, Any]]:
        key = (location.pack_id, location.shard_path)
        cached = self._shard_cache.get(key)
        if cached is not None:
            return cached
        path = _safe_asset_path(self._release_dir(location.pack_id), location.shard_path)
        if not path.is_file():
            raise CorpusUnavailableError(f"PRTS 分片缺失：{location.pack_id}")
        try:
            records = []
            size = 0
            for raw in _iter_gzip_lines(path, account=self._account_query_decompressed):
                if raw.strip():
                    size += len(raw.encode("utf-8"))
                    records.append(json.loads(raw))
        except (OSError, json.JSONDecodeError) as exc:
            raise CorpusError(f"读取 PRTS 分片失败：{path}: {exc}") from exc
        if self._cache_bytes + size <= MAX_STORE_CACHE_BYTES:
            self._shard_cache[key] = records
            self._cache_bytes += size
        return records

    def _load_index(self, pack_id: str, path: str) -> dict[str, list[int]]:
        key = (pack_id, path)
        cached = self._index_cache.get(key)
        if cached is not None:
            return cached
        index_path = _safe_asset_path(self._release_dir(pack_id), path)
        if not index_path.is_file():
            raise CorpusUnavailableError(f"PRTS 倒排索引缺失：{pack_id}")
        raw = _read_gzip_bytes(index_path, account=self._account_query_decompressed)
        if raw[:8] not in (b"PRTSNG2\0", b"PRTSTG1\0"):
            raise CorpusError(f"PRTS 倒排索引格式未知：{index_path}")
        count = int.from_bytes(raw[8:12], "little")
        table_start = 12
        payload_start = table_start + (count + 1) * 4
        if payload_start > len(raw):
            raise CorpusError(f"PRTS 倒排索引偏移表损坏：{index_path}")
        offsets = [
            int.from_bytes(raw[table_start + index * 4 : table_start + index * 4 + 4], "little")
            for index in range(count + 1)
        ]
        result: dict[str, list[int]] = {}
        for index in range(count):
            cursor = payload_start + offsets[index]
            end = payload_start + offsets[index + 1]
            length, cursor = _read_varint(raw, cursor, end)
            gram = raw[cursor : cursor + length].decode("utf-8")
            cursor += length
            posting_count, cursor = _read_varint(raw, cursor, end)
            postings: list[int] = []
            current = 0
            for _ in range(posting_count):
                delta, cursor = _read_varint(raw, cursor, end)
                current += delta
                postings.append(current)
            result[gram] = postings
        if self._cache_bytes + len(raw) <= MAX_STORE_CACHE_BYTES:
            self._index_cache[key] = result
            self._cache_bytes += len(raw)
        return result

    def _candidate_locations(self, query: str, pack_ids: list[str] | None = None) -> list[DocumentLocation] | None:
        grams = _ngrams(query)
        if not grams:
            return None
        candidates: list[DocumentLocation] = []
        selected_packs = set(self._manifests if pack_ids is None else pack_ids)
        has_index = False
        for pack_id, manifest in self._manifests.items():
            if pack_id not in selected_packs:
                continue
            search = manifest.get("search_index")
            if not isinstance(search, dict) or not search.get("shards"):
                continue
            has_index = True
            per_gram: dict[str, set[int]] = {gram: set() for gram in grams}
            for descriptor in search.get("shards", []):
                if not isinstance(descriptor, dict):
                    continue
                first = str(descriptor.get("first_ngram") or descriptor.get("first_trigram") or "").encode("utf-8")
                last = str(descriptor.get("last_ngram") or descriptor.get("last_trigram") or "").encode("utf-8")
                relevant = [gram for gram in grams if first <= gram.encode("utf-8") <= last]
                if not relevant:
                    continue
                index = self._load_index(pack_id, str(descriptor.get("path") or ""))
                for gram in relevant:
                    per_gram[gram].update(index.get(gram, []))
            intersection: set[int] | None = None
            for gram in grams:
                values = per_gram[gram]
                intersection = values if intersection is None else intersection.intersection(values)
            candidates.extend(
                location
                for location in self._locations.values()
                if location.pack_id == pack_id and location.search_index_id in (intersection or set())
            )
        return candidates if has_index else None

    def _matches_filters(self, summary: dict[str, Any], record: dict[str, Any], filters: dict[str, Any]) -> bool:
        if filters.get("games") and _game(summary) not in filters["games"]:
            return False
        if filters.get("resource_types") and _resource_type(summary) not in filters["resource_types"]:
            return False
        metadata = " ".join(
            str(summary.get(key) or "")
            for key in (
                "display_title",
                "character_name",
                "activity_name",
                "story_name",
                "collection_name",
            )
        )
        metadata_text = _normalize(metadata)
        for key in ("character_names", "activity_names", "entity_names"):
            if filters.get(key) and not any(_normalize(item) in metadata_text for item in filters[key]):
                return False
        if filters.get("speakers"):
            speakers = {
                str(item.get("speaker_raw") or "") for item in record.get("lines", []) if isinstance(item, dict)
            }
            if not speakers.intersection(filters["speakers"]):
                return False
        return True

    @_serialized
    def search(
        self,
        query: str,
        *,
        pack_ids: list[str] | None = None,
        limit: int = 5,
        pointer: Any = _CURRENT_POINTER,
        **filters: Any,
    ) -> dict[str, Any]:
        self._load(pointer, pack_ids, require_search_index=True)
        normalized_query = _normalize(query)
        locations = self._candidate_locations(normalized_query, pack_ids) if normalized_query else None
        if locations is None:
            locations = list(self._locations.values())
        selected_packs = set(self._manifests if pack_ids is None else pack_ids)
        results: list[dict[str, Any]] = []
        for location in locations:
            if location.pack_id not in selected_packs:
                continue
            records = self._load_shard(location)
            if location.record_index >= len(records):
                continue
            record = records[location.record_index]
            if not isinstance(record, dict) or not self._matches_filters(location.summary, record, filters):
                continue
            lines = record.get("lines") if isinstance(record.get("lines"), list) else []
            matches = []
            for line in lines:
                if not isinstance(line, dict):
                    continue
                if normalized_query and normalized_query not in _normalize(_line_text(line)):
                    continue
                matches.append({
                    "line": int(line.get("line_number") or 0),
                    "speaker": str(line.get("speaker_raw") or ""),
                    "text": _bounded_text(line.get("text")),
                })
                if len(matches) >= 3:
                    break
            title_hit = normalized_query and normalized_query in _normalize(location.summary.get("display_title"))
            if normalized_query and not matches and not title_hit:
                continue
            line_start = matches[0]["line"] if matches else None
            line_end = matches[-1]["line"] if matches else None
            title = str(location.summary.get("display_title") or location.document_id)
            result = {
                "game": _game(location.summary),
                "title": title,
                "resource_type": _resource_type(location.summary),
                "authority": str(self._manifests.get(location.pack_id, {}).get("authority") or ""),
                "document_uid": _document_uid(location.document_id),
                "source_ref_prefix": str(location.summary.get("source_ref_prefix") or ""),
                "matches": matches,
                "citation": f"《{title}》" + (f"第 {line_start}-{line_end} 行" if line_start else ""),
            }
            results.append(result)
        results.sort(key=lambda item: (0 if item["matches"] else 1, item["title"]))
        return {
            "query": query,
            "data_version": self._data_version,
            "count": min(len(results), max(1, limit)),
            "items": results[: max(1, limit)],
        }

    @_serialized
    def read(
        self,
        *,
        document_uid: str = "",
        document_id: str = "",
        display_title: str = "",
        source_ref: str = "",
        start_line: int = 1,
        end_line: int | None = None,
        max_lines: int = 80,
        max_chars: int = 12000,
        pack_ids: Iterable[str] | None = None,
        pointer: Any = _CURRENT_POINTER,
    ) -> dict[str, Any]:
        self._load(pointer, pack_ids)
        location = None
        center_line = None
        if document_uid:
            location = self._by_uid.get(document_uid.strip())
        elif document_id:
            location = self._by_id.get(document_id.strip())
        elif display_title:
            matches = self._by_title.get(_normalize(display_title), [])
            if len(matches) > 1:
                raise CorpusError("资料标题有歧义，请使用 document_uid")
            location = matches[0] if matches else None
        elif source_ref:
            prefix, separator, line = source_ref.rpartition(":L")
            location = next(
                (item for item in self._by_id.values() if item.summary.get("source_ref_prefix") == prefix),
                None,
            )
            if separator and line.isdigit():
                center_line = int(line)
        if location is not None and pack_ids is not None and location.pack_id not in set(pack_ids):
            location = None
        if location is None:
            raise CorpusNotFoundError("找不到指定的 PRTS 文档")
        if center_line is not None:
            start_line = max(1, center_line - 3)
            end_line = center_line + 3
        records = self._load_shard(location)
        if location.record_index >= len(records):
            raise CorpusNotFoundError("PRTS 文档记录不存在")
        record = records[location.record_index]
        lines = record.get("lines") if isinstance(record.get("lines"), list) else []
        start = max(1, int(start_line))
        end = min(len(lines), int(end_line or len(lines)), start + max(1, max_lines) - 1)
        selected: list[dict[str, Any]] = []
        char_count = 0
        truncated = False
        for line in lines:
            if not isinstance(line, dict) or not start <= int(line.get("line_number") or 0) <= end:
                continue
            text = str(line.get("text") or "")
            remaining = max(0, int(max_chars) - char_count)
            if not remaining:
                truncated = True
                break
            if len(text) > remaining:
                line = {**line, "text": f"{text[: max(0, remaining - 1)]}…"}
                truncated = True
            char_count += len(str(line.get("text") or ""))
            selected.append(line)
            if len(selected) >= max(1, max_lines) or truncated:
                break
        title = str(location.summary.get("display_title") or location.document_id)
        return {
            "data_version": self._data_version,
            "game": _game(location.summary),
            "title": title,
            "resource_type": _resource_type(location.summary),
            "authority": str(self._manifests.get(location.pack_id, {}).get("authority") or ""),
            "document_uid": _document_uid(location.document_id),
            "lines": [
                {
                    "line": int(line.get("line_number") or 0),
                    "speaker": str(line.get("speaker_raw") or ""),
                    "text": str(line.get("text") or ""),
                    "source_ref": f"{location.summary.get('source_ref_prefix')}:L{line.get('line_number')}",
                }
                for line in selected
            ],
            "has_more": truncated or end < len(lines),
            "citation": f"《{title}》第 {start}-{end} 行",
        }


def _read_varint(raw: bytes, cursor: int, end: int) -> tuple[int, int]:
    value = 0
    shift = 0
    while cursor < end and shift <= 49:
        byte = raw[cursor]
        cursor += 1
        value += (byte & 0x7F) << shift
        if not byte & 0x80:
            return value, cursor
        shift += 7
    raise CorpusError("PRTS 倒排索引 varint 损坏")


def _bounded_text(value: Any, limit: int = MAX_MATCH_CHARS) -> str:
    text = str(value or "")
    return text if len(text) <= limit else f"{text[: limit - 1]}…"
