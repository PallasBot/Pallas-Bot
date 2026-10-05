"""控制台 / CLI：MongoDB、PostgreSQL 逻辑备份。"""

from __future__ import annotations

import errno
import hashlib
import json
import os
import re
import secrets
import shutil
import stat
import subprocess
import tempfile
import zipfile
from dataclasses import dataclass, field
from datetime import datetime
from operator import itemgetter
from pathlib import Path, PurePosixPath
from typing import Any, Literal

from pallas.core.foundation.db import _cfg, get_db_backend
from pallas.core.foundation.paths import PROJECT_ROOT

MongoScope = Literal["full", "important"]
PgFormat = Literal["custom", "plain", "directory"]

# 控制台在未检测到 CLI 时展示给用户的官方下载页
_TOOL_DOWNLOAD: dict[str, dict[str, str]] = {
    "mongodump": {
        "label": "MongoDB Database Tools",
        "url": "https://www.mongodb.com/try/download/database-tools",
        "hint": "安装后将安装目录加入 PATH，或把 mongodump.exe 所在目录加入系统环境变量。",
    },
    "pg_dump": {
        "label": "PostgreSQL 客户端（含 pg_dump）",
        "url": "https://www.postgresql.org/download/",
        "hint": "Windows 可选用 EDB 安装包；安装后确认 pg_dump 在 PATH 中。",
    },
    "pg_restore": {
        "label": "PostgreSQL 客户端（含 pg_restore）",
        "url": "https://www.postgresql.org/download/",
        "hint": "通常与 pg_dump 同包安装；确认 pg_restore / psql 在 PATH 中。",
    },
    "mongorestore": {
        "label": "MongoDB Database Tools",
        "url": "https://www.mongodb.com/try/download/database-tools",
        "hint": "安装后将安装目录加入 PATH，或把 mongorestore 所在目录加入系统环境变量。",
    },
}

_MONGO_IMPORTANT_COLLECTIONS: tuple[str, ...] = (
    "blacklist",
    "blacklist_audit",
    "config",
    "group_config",
    "user_config",
    "context",
)

_IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,62}$")
_BACKUP_MANIFEST_NAME = "manifest.json"
_BACKUP_MANIFEST_SCHEMA = "pallas-db-backup/v1"
_STAGING_MARKER = ".staging-"


@dataclass
class BackupResult:
    ok: bool
    backend: str
    scope: str
    output_dir: str
    artifacts: list[str] = field(default_factory=list)
    size_bytes: int = 0
    message: str = ""
    command: list[str] = field(default_factory=list)


def default_backup_parent() -> Path:
    return (PROJECT_ROOT / "backups").resolve()


def resolve_backup_parent(user_path: str | None) -> Path:
    """解析用户指定的备份父目录。"""
    raw = (user_path or "").strip()
    if not raw:
        parent = default_backup_parent()
    else:
        p = Path(raw)
        parent = (PROJECT_ROOT / p).resolve() if not p.is_absolute() else p.resolve()
    if parent.name in ("", ".", ".."):
        raise ValueError("无效的备份目录")
    parent.mkdir(parents=True, exist_ok=True)
    return parent


def make_backup_run_dir(parent: Path, backend: str, *, label: str = "") -> Path:
    stamp = datetime.now().strftime("%Y_%m_%d_%H_%M_%S")
    suffix = re.sub(r"[^\w\-]+", "_", label.strip())[:40] if label.strip() else ""
    name = f"{backend}_{stamp}" + (f"_{suffix}" if suffix else "")
    dest = (parent / name).resolve()
    dest.mkdir(parents=True, exist_ok=False)
    return dest


def _unique_backup_target(parent: Path, backend: str, label: str) -> Path:
    stamp = datetime.now().strftime("%Y_%m_%d_%H_%M_%S")
    suffix = re.sub(r"[^\w\-]+", "_", label.strip())[:40] if label.strip() else ""
    name = f"{backend}_{stamp}" + (f"_{suffix}" if suffix else "") + f"_{secrets.token_hex(4)}"
    return parent / name


def _new_backup_staging(target: Path) -> Path:
    staging = target.with_name(f".{target.name}{_STAGING_MARKER}{secrets.token_hex(4)}")
    staging.mkdir(mode=0o700)
    return staging


def _staging_target(staging: Path) -> Path | None:
    name = staging.name
    if not name.startswith(".") or _STAGING_MARKER not in name:
        return None
    return staging.with_name(name[1:].rsplit(_STAGING_MARKER, 1)[0])


def _validate_backup_run_dir(parent: Path, backend: str, run_dir: Path | None) -> Path | None:
    if run_dir is None:
        return None
    if run_dir.is_symlink():
        raise ValueError("备份输出目录不能是符号链接")
    requested = run_dir.absolute()
    if not requested.is_dir():
        raise ValueError("备份输出目录不存在")
    target = _staging_target(requested)
    if requested.name.startswith("."):
        if target is None:
            raise ValueError("无效的隐藏备份暂存目录")
        if requested.parent != parent or not target.name.startswith(f"{backend}_"):
            raise ValueError("备份暂存目录不在目标文件系统内")
        if any(requested.iterdir()):
            raise ValueError("显式备份暂存目录必须为空")
        if target.exists() or target.is_symlink():
            raise FileExistsError(f"备份目标已存在: {target}")
        return requested
    if any(requested.iterdir()):
        raise ValueError("显式备份输出目录必须为空")
    return requested


def _remove_owned_staging(staging: Path) -> None:
    if not staging.is_symlink():
        shutil.rmtree(staging, ignore_errors=True)


def _begin_backup_run(
    parent: Path,
    backend: str,
    label: str,
    run_dir: Path | None,
) -> tuple[Path, Path, bool]:
    if run_dir is None:
        while True:
            target = _unique_backup_target(parent, backend, label)
            if target.exists() or target.is_symlink():
                continue
            try:
                return _new_backup_staging(target), target, True
            except FileExistsError:
                continue

    requested = _validate_backup_run_dir(parent, backend, run_dir)
    assert requested is not None
    target = _staging_target(requested)
    if target is not None:
        return requested, target, False
    try:
        staging = _new_backup_staging(requested)
    except OSError as e:
        raise _friendly_backup_error(e, requested.parent) from e
    return staging, requested, True


def _publish_backup(staging: Path, target: Path) -> None:
    if staging.is_symlink() or target.is_symlink():
        raise ValueError("备份路径不能是符号链接")
    removed_empty_target = False
    if target.exists():
        if not target.is_dir() or any(target.iterdir()):
            raise ValueError("备份目标已存在且非空")
        target.rmdir()
        removed_empty_target = True
    try:
        staging.rename(target)
    except BaseException:
        if removed_empty_target and not target.exists():
            target.mkdir()
        raise


def _friendly_backup_error(error: OSError, target: Path) -> RuntimeError:
    if error.errno == errno.ENOSPC:
        return RuntimeError(f"备份目标磁盘空间不足：{target}")
    if error.errno in (errno.EACCES, errno.EROFS):
        return RuntimeError(f"备份目标不可写：{target}")
    return RuntimeError(f"备份目标操作失败：{target}（{error.strerror or error}）")


def _check_backup_target(staging: Path) -> None:
    target_fs = staging.parent
    try:
        with tempfile.NamedTemporaryFile(prefix=".pallas-backup-write-test-", dir=target_fs) as probe:
            probe.write(b"\0")
            probe.flush()
        free_bytes = shutil.disk_usage(target_fs).free
    except OSError as e:
        raise _friendly_backup_error(e, target_fs) from e
    if free_bytes <= 0:
        raise RuntimeError(f"备份目标磁盘空间不足：{target_fs}")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _backup_file_entries(run_dir: Path) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    for root, dirs, files in os.walk(run_dir, followlinks=False):
        base = Path(root)
        if any((base / name).is_symlink() for name in dirs):
            raise ValueError("备份产物不能包含符号链接")
        for name in files:
            path = base / name
            if path.is_symlink() or not path.is_file():
                raise ValueError("备份产物包含不支持的文件类型")
            if path == run_dir / _BACKUP_MANIFEST_NAME:
                continue
            entries.append({
                "path": path.relative_to(run_dir).as_posix(),
                "size_bytes": path.stat().st_size,
                "sha256": _sha256(path),
            })
    return sorted(entries, key=itemgetter("path"))


def _write_backup_manifest(
    run_dir: Path,
    *,
    backend: str,
    backup_format: str,
    scope: str,
    tool_name: str,
    tool_version: str,
    server_version: str,
    validation_method: str,
) -> None:
    _secure_backup_tree(run_dir)
    manifest = {
        "schema": _BACKUP_MANIFEST_SCHEMA,
        "backend": backend,
        "format": backup_format,
        "scope": scope,
        "tool": {"name": tool_name, "version": tool_version},
        "server_version": server_version,
        "files": _backup_file_entries(run_dir),
        "validation_method": validation_method,
    }
    path = run_dir / _BACKUP_MANIFEST_NAME
    if path.exists():
        raise ValueError("备份产物占用了 manifest.json")
    tmp_path = run_dir / f".{_BACKUP_MANIFEST_NAME}.{secrets.token_hex(4)}.tmp"
    try:
        tmp_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        tmp_path.chmod(0o600)
        tmp_path.replace(path)
    finally:
        tmp_path.unlink(missing_ok=True)


def _verify_backup_manifest(run_dir: Path) -> bool:
    path = run_dir / _BACKUP_MANIFEST_NAME
    if path.is_symlink():
        raise ValueError("备份清单无效")
    if not path.exists():
        return False
    if not path.is_file():
        raise ValueError("备份清单无效")
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        raise ValueError("备份清单无法读取") from e
    if not isinstance(manifest, dict) or manifest.get("schema") != _BACKUP_MANIFEST_SCHEMA:
        return False
    if (
        manifest.get("backend") not in ("postgres", "mongodb")
        or manifest.get("backend") != backup_run_backend(run_dir)
        or not isinstance(manifest.get("format"), str)
        or not isinstance(manifest.get("scope"), str)
        or not isinstance(manifest.get("tool"), dict)
        or not isinstance(manifest["tool"].get("name"), str)
        or not isinstance(manifest["tool"].get("version"), str)
        or not isinstance(manifest.get("server_version"), str)
        or not isinstance(manifest.get("validation_method"), str)
        or not isinstance(manifest.get("files"), list)
    ):
        raise ValueError("备份清单格式无效")

    actual = {entry["path"]: entry for entry in _backup_file_entries(run_dir)}
    declared: set[str] = set()
    for item in manifest["files"]:
        if not isinstance(item, dict) or not isinstance(item.get("path"), str):
            raise ValueError("备份清单文件路径无效")
        raw_path = item["path"]
        relative = PurePosixPath(raw_path)
        if (
            not raw_path
            or "\\" in raw_path
            or relative.is_absolute()
            or any(part in ("", ".", "..") for part in relative.parts)
            or relative.as_posix() != raw_path
            or raw_path in declared
        ):
            raise ValueError("备份清单包含越界或重复路径")
        declared.add(raw_path)
        if not isinstance(item.get("size_bytes"), int) or item["size_bytes"] < 0:
            raise ValueError("备份清单文件大小无效")
        expected_hash = item.get("sha256")
        if not isinstance(expected_hash, str) or not re.fullmatch(r"[0-9a-f]{64}", expected_hash):
            raise ValueError("备份清单校验值无效")
        recorded = actual.get(raw_path)
        if recorded is None or recorded["size_bytes"] != item["size_bytes"] or recorded["sha256"] != expected_hash:
            raise ValueError(f"备份文件校验失败：{raw_path}")
    if declared != set(actual):
        raise ValueError("备份文件与清单不一致")
    return True


def _assert_no_symlinks(path: Path) -> None:
    if path.is_symlink():
        raise ValueError("备份产物不能包含符号链接")
    if not path.is_dir():
        return
    for root, dirs, files in os.walk(path, followlinks=False):
        base = Path(root)
        for name in dirs:
            mode = (base / name).lstat().st_mode
            if stat.S_ISLNK(mode):
                raise ValueError("备份产物不能包含符号链接")
            if not stat.S_ISDIR(mode):
                raise ValueError("备份产物包含不支持的文件类型")
        for name in files:
            mode = (base / name).lstat().st_mode
            if stat.S_ISLNK(mode):
                raise ValueError("备份产物不能包含符号链接")
            if not stat.S_ISREG(mode):
                raise ValueError("备份产物包含不支持的文件类型")


def _secure_backup_tree(path: Path) -> None:
    if path.is_symlink() or not path.is_dir():
        raise ValueError("备份暂存目录无效")
    _assert_no_symlinks(path)
    path.chmod(0o700, follow_symlinks=False)
    for root, dirs, files in os.walk(path, followlinks=False):
        base = Path(root)
        for name in dirs:
            (base / name).chmod(0o700, follow_symlinks=False)
        for name in files:
            (base / name).chmod(0o600, follow_symlinks=False)


def dir_size_bytes(path: Path) -> int:
    if path.is_file():
        return path.stat().st_size
    total = 0
    for root, _dirs, files in os.walk(path):
        for fn in files:
            try:
                total += (Path(root) / fn).stat().st_size
            except OSError:
                pass
    return total


def tool_on_path(name: str) -> bool:
    return shutil.which(name) is not None


def pg_tool_candidates(tool: str) -> list[Path]:
    """Find PostgreSQL client tools without relying on the first PATH match."""
    candidates: list[Path] = []
    bindirs: set[Path] = set()
    path_dirs = [Path(part or ".") for part in os.environ.get("PATH", "").split(os.pathsep)]
    candidates.extend(directory / tool for directory in path_dirs)
    found_on_path = shutil.which(tool)
    if found_on_path:
        candidates.append(Path(found_on_path))
    pg_config_paths = [directory / "pg_config" for directory in path_dirs]
    pg_config = shutil.which("pg_config")
    if pg_config:
        pg_config_paths.append(Path(pg_config))
    for pg_config_path in pg_config_paths:
        if not pg_config_path.is_file() or not os.access(pg_config_path, os.X_OK):
            continue
        try:
            result = subprocess.run(
                [str(pg_config_path), "--bindir"],
                capture_output=True,
                text=True,
                timeout=3,
                check=False,
            )
            if result.returncode == 0 and result.stdout.strip():
                bindirs.add(Path(result.stdout.strip()))
        except (OSError, subprocess.TimeoutExpired):
            pass
    bindirs.update(Path("/usr/lib/postgresql").glob("*/bin"))
    candidates.extend(directory / tool for directory in sorted(bindirs))

    found: list[Path] = []
    seen: set[Path] = set()
    for path in candidates:
        try:
            resolved = path.resolve()
            if resolved in seen or not resolved.is_file() or not os.access(resolved, os.X_OK):
                continue
            seen.add(resolved)
            found.append(path.absolute())
        except OSError:
            continue
    return found


def pg_tool_version(path: Path) -> tuple[str, int] | None:
    try:
        result = subprocess.run(
            [str(path), "--version"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    match = re.search(r"\(PostgreSQL\)\s+(\d+(?:\.\d+){0,2})", result.stdout or result.stderr)
    if not match:
        return None
    version = match.group(1)
    try:
        major = int(version.split(".", 1)[0])
    except ValueError:
        return None
    return version, major


def select_pg_tool(
    tool: str,
    server_major: int | None = None,
    *,
    exact_major: bool = False,
) -> tuple[Path, str, int]:
    available = [(path, *version) for path in pg_tool_candidates(tool) if (version := pg_tool_version(path))]
    if not available:
        raise RuntimeError(missing_tool_message(tool))
    if server_major is None:
        return max(available, key=lambda item: tuple(int(part) for part in item[1].split(".")))
    exact = [item for item in available if item[2] == server_major]
    if exact:
        return max(exact, key=lambda item: tuple(int(part) for part in item[1].split(".")))
    if exact_major:
        raise RuntimeError(f"未找到与 PostgreSQL {server_major} 同主版本的 {tool}，无法验证备份")
    newer = [item for item in available if item[2] > server_major]
    if newer:
        return min(newer, key=lambda item: (item[2], tuple(int(part) for part in item[1].split("."))))
    raise RuntimeError(f"未找到兼容 PostgreSQL {server_major} 的 {tool}（不接受低版本客户端）")


def _psql_query(query: str) -> str:
    psql, _version, _major = select_pg_tool("psql")
    env = os.environ.copy()
    env.update(_postgres_restore_env())
    env["PGCONNECT_TIMEOUT"] = "5"
    try:
        result = subprocess.run(
            [str(psql), "-X", "-A", "-t", "-w", *_postgres_base_cmd(), "-c", query],
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=10,
            check=False,
        )
    except subprocess.TimeoutExpired as e:
        raise RuntimeError("PostgreSQL 只读探测超时") from e
    if result.returncode:
        detail = (result.stderr or "").strip()
        raise RuntimeError(f"PostgreSQL 只读探测失败：{detail or result.returncode}")
    return result.stdout.strip()


def postgres_server_info() -> tuple[int, str]:
    raw_version = _psql_query("SHOW server_version_num")
    try:
        version_num = int(raw_version)
    except ValueError as e:
        raise RuntimeError("PostgreSQL 返回了无效的 server_version_num") from e
    major = version_num // 10000
    minor = version_num % 10000 if major >= 10 else (version_num % 10000) // 100
    version = f"{major}.{minor}"
    return major, version


def backup_info() -> dict[str, Any]:
    backend = get_db_backend()
    if backend in ("postgres", "postgresql", "pg"):
        b = "postgres"
        tool = "pg_dump"
        conn = {
            "host": _pg_host(),
            "port": int(_cfg("PG_PORT", "5432")),
            "database": _cfg("PG_DB", "PallasBot"),
            "user": _cfg("PG_USER", "") or None,
        }
    else:
        b = "mongodb"
        tool = "mongodump"
        conn = {
            "host": _cfg("MONGO_HOST", "127.0.0.1"),
            "port": int(_cfg("MONGO_PORT", "27017")),
            "database": _cfg("MONGO_DB", "PallasBot"),
            "user": _cfg("MONGO_USER", "") or None,
        }
    meta = _TOOL_DOWNLOAD.get(tool, {})
    restore_tool = "pg_restore" if b == "postgres" else "mongorestore"
    if b == "postgres":
        try:
            select_pg_tool(tool)
            available = True
        except RuntimeError:
            available = False
        try:
            select_pg_tool(restore_tool)
            restore_available = True
        except RuntimeError:
            try:
                select_pg_tool("psql")
                restore_available = True
            except RuntimeError:
                restore_available = False
    else:
        available = tool_on_path(tool)
        restore_available = tool_on_path(restore_tool)
    return {
        "backend": b,
        "default_output_parent": str(default_backup_parent()),
        "tool_name": tool,
        "tool_available": available,
        "restore_tool_name": restore_tool,
        "restore_tool_available": restore_available,
        "tool_download_label": meta.get("label", tool),
        "tool_download_url": meta.get("url", ""),
        "tool_install_hint": meta.get("hint", ""),
        "connection": conn,
        "mongo_scopes": ["full", "important"],
        "postgres_formats": ["custom", "plain", "directory"],
    }


def missing_tool_message(tool: str) -> str:
    meta = _TOOL_DOWNLOAD.get(tool, {})
    label = meta.get("label", tool)
    url = meta.get("url", "")
    hint = meta.get("hint", "")
    parts = [f"未找到 {tool}，请先安装 {label}。"]
    if url:
        parts.append(f"下载：{url}")
    if hint:
        parts.append(hint)
    return " ".join(parts)


def _pg_host() -> str:
    host = _cfg("PG_HOST", "").strip()
    return host or _cfg("MONGO_HOST", "127.0.0.1")


def _run_checked(cmd: list[str], *, env: dict[str, str] | None = None) -> None:
    merged = os.environ.copy()
    if env:
        merged.update(env)
    try:
        proc = subprocess.run(
            cmd,
            env=merged,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=3600,
            check=False,
        )
    except subprocess.TimeoutExpired:
        tool = Path(cmd[0]).name if cmd else "数据库工具"
        raise RuntimeError(f"{tool} 执行超时") from None
    if proc.returncode != 0:
        err = (proc.stderr or proc.stdout or "").strip() or f"退出码 {proc.returncode}"
        cmd_hint_parts: list[str] = []
        redact_next = False
        for part in cmd:
            if redact_next:
                cmd_hint_parts.append("******")
                redact_next = False
            else:
                cmd_hint_parts.append(part)
                redact_next = part == "--password"
        cmd_hint = " ".join(cmd_hint_parts[:6])
        if len(cmd_hint_parts) > 6:
            cmd_hint += " …"
        raise RuntimeError(f"{err}（命令: {cmd_hint}）")


def is_backup_run_dir(path: Path) -> bool:
    name = path.name
    return name.startswith(("postgres_", "mongodb_"))


def backup_run_backend(path: Path) -> str:
    return "postgres" if path.name.startswith("postgres_") else "mongodb"


def assert_deletable_backup_run(target: Path, parent: Path) -> None:
    """校验目标为 parent 下的合法备份子目录。"""
    resolved = target.resolve()
    parent_resolved = parent.resolve()
    if resolved == parent_resolved:
        raise ValueError("不能删除备份父目录本身")
    try:
        resolved.relative_to(parent_resolved)
    except ValueError as e:
        raise ValueError("备份路径不在允许的父目录内") from e
    if not resolved.is_dir():
        raise ValueError("备份目录不存在")
    if not is_backup_run_dir(resolved):
        raise ValueError("不是合法的备份目录")


def list_backup_runs(*, output_parent: str | None = None) -> list[dict[str, Any]]:
    parent = resolve_backup_parent(output_parent)
    if not parent.is_dir():
        return []
    entries: list[dict[str, Any]] = []
    for child in parent.iterdir():
        if not child.is_dir() or not is_backup_run_dir(child) or not _has_recognized_backup_artifacts(child):
            continue
        try:
            mtime = child.stat().st_mtime
        except OSError:
            mtime = 0.0
        entries.append({
            "name": child.name,
            "path": str(child.resolve()),
            "backend": backup_run_backend(child),
            "size_bytes": dir_size_bytes(child),
            "modified_at": datetime.fromtimestamp(mtime).isoformat(timespec="seconds"),
        })
    entries.sort(key=lambda row: row.get("modified_at") or "", reverse=True)
    return entries


def normalize_pg_tables(tables: list[str] | None) -> list[str] | None:
    if not tables:
        return None
    out: list[str] = []
    for raw in tables:
        name = raw.strip()
        if not name:
            continue
        if not _IDENTIFIER_RE.match(name):
            raise ValueError(f"无效的 PostgreSQL 表名: {raw}")
        if name not in out:
            out.append(name)
    return out or None


def normalize_mongo_collections(collections: list[str] | None) -> list[str] | None:
    if not collections:
        return None
    out: list[str] = []
    for raw in collections:
        name = raw.strip()
        if not name:
            continue
        if not _IDENTIFIER_RE.match(name):
            raise ValueError(f"无效的 MongoDB 集合名: {raw}")
        if name not in out:
            out.append(name)
    return out or None


def _browse_allowed_roots() -> list[Path]:
    """浏览允许的根：项目根，以及符号链接解析后的默认备份父目录（可能指向外部挂载）。"""
    roots = [PROJECT_ROOT.resolve()]
    default_parent = default_backup_parent()
    if default_parent != roots[0]:
        roots.append(default_parent)
    return roots


def is_browse_allowed(path: Path) -> bool:
    resolved = path.resolve()
    for root in _browse_allowed_roots():
        try:
            resolved.relative_to(root)
            return True
        except ValueError:
            pass
        try:
            root.relative_to(resolved)
            return True
        except ValueError:
            pass
    return False


def browse_backup_directories(*, path: str | None = None) -> dict[str, Any]:
    project = PROJECT_ROOT.resolve()
    if path and path.strip():
        raw = Path(path.strip())
        current = (project / raw).resolve() if not raw.is_absolute() else raw.resolve()
    else:
        current = default_backup_parent().resolve()
        if not current.exists():
            current = project
    if not is_browse_allowed(current):
        raise ValueError("目录不在允许范围内")
    if not current.exists():
        raise ValueError("目录不存在")
    if not current.is_dir():
        raise ValueError("不是有效目录")

    parent_path: str | None = None
    parent = current.parent
    if parent != current and is_browse_allowed(parent):
        parent_path = str(parent.resolve())

    entries: list[dict[str, str]] = []
    try:
        for child in sorted(current.iterdir(), key=lambda p: p.name.lower()):
            if not child.is_dir() or child.name.startswith("."):
                continue
            entries.append({
                "name": child.name,
                "path": str(child.resolve()),
                "kind": "dir",
            })
    except OSError:
        pass

    return {
        "current": str(current.resolve()),
        "parent": parent_path,
        "entries": entries,
        "default_path": str(default_backup_parent().resolve()),
        "project_root": str(project),
    }


def prepare_backup_download(path: str, *, output_parent: str | None = None) -> tuple[Path, str]:
    parent = resolve_backup_parent(output_parent)
    target = Path(path.strip()).resolve()
    assert_deletable_backup_run(target, parent)
    _assert_no_symlinks(target)
    _verify_backup_manifest(target)
    zip_name = f"{target.name}.zip"
    work_dir: Path | None = None
    try:
        work_dir = Path(tempfile.mkdtemp(prefix=".pallas-backup-download-", dir=parent))
        work_dir.chmod(0o700)
        zip_path = work_dir / zip_name
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for root, _dirs, files in os.walk(target):
                for fn in files:
                    fp = Path(root) / fn
                    try:
                        arcname = fp.relative_to(target)
                    except ValueError:
                        continue
                    zf.write(fp, arcname)
        zip_path.chmod(0o600)
        return zip_path, zip_name
    except BaseException as e:
        if work_dir is not None:
            shutil.rmtree(work_dir, ignore_errors=True)
        if isinstance(e, OSError) and e.errno == errno.ENOSPC:
            raise _friendly_backup_error(e, parent) from e
        raise


def cleanup_backup_download(path: Path) -> None:
    try:
        path.unlink(missing_ok=True)
        if path.parent.name.startswith(".pallas-backup-download-"):
            path.parent.rmdir()
    except OSError:
        pass


def delete_backup_runs(
    paths: list[str],
    *,
    output_parent: str | None = None,
) -> dict[str, Any]:
    if not paths:
        raise ValueError("未指定要删除的备份")
    parent = resolve_backup_parent(output_parent)
    deleted: list[str] = []
    for raw in paths:
        target = Path(raw.strip())
        if not raw.strip():
            continue
        assert_deletable_backup_run(target, parent)
        shutil.rmtree(target.resolve())
        deleted.append(str(target.resolve()))
    if not deleted:
        raise ValueError("未指定要删除的备份")
    return {"deleted": deleted, "count": len(deleted)}


def run_postgres_backup(
    *,
    output_parent: str | None = None,
    label: str = "",
    pg_format: PgFormat = "custom",
    pg_tables: list[str] | None = None,
    run_dir: Path | None = None,
) -> BackupResult:
    tables = normalize_pg_tables(pg_tables)
    parent = resolve_backup_parent(output_parent)
    run_dir = _validate_backup_run_dir(parent, "postgres", run_dir)
    server_major, server_version = postgres_server_info()
    dump_tool, dump_version, dump_major = select_pg_tool("pg_dump", server_major)
    restore_tool: Path | None = None
    if pg_format != "plain":
        restore_tool, _restore_version, _restore_major = select_pg_tool("pg_restore", dump_major, exact_major=True)
    host = _pg_host()
    port = str(int(_cfg("PG_PORT", "5432")))
    user = _cfg("PG_USER", "").strip()
    password = _cfg("PG_PASSWORD", "")
    db_name = _cfg("PG_DB", "PallasBot")
    env: dict[str, str] = {}
    if password:
        env["PGPASSWORD"] = password
    safe_db = re.sub(r"[^\w\-]+", "_", db_name)
    targets = tables or [None]
    staged_artifacts: list[Path] = []
    commands: list[list[str]] = []
    scope = "tables" if tables else pg_format
    staging, target, owned_staging = _begin_backup_run(parent, "postgres", label, run_dir)
    try:
        _check_backup_target(staging)
        for table in targets:
            safe_name = re.sub(r"[^\w\-]+", "_", table) if table else safe_db
            cmd = [str(dump_tool), "-h", host, "-p", port, "-d", db_name]
            if user:
                cmd.extend(["-U", user])
            if table:
                cmd.extend(["-t", table])
            if pg_format == "custom":
                artifact = staging / f"{safe_name}.dump"
                cmd.extend(["-Fc", "-f", str(artifact)])
            elif pg_format == "plain":
                artifact = staging / f"{safe_name}.sql"
                cmd.extend(["-f", str(artifact)])
            else:
                artifact = staging / f"pg_directory_{safe_name}"
                cmd.extend(["-Fd", "-f", str(artifact)])
            _run_checked(cmd, env=env)
            staged_artifacts.append(artifact)
            commands.append(cmd)

        validation_methods: set[str] = set()
        for artifact in staged_artifacts:
            if pg_format == "plain":
                _validate_plain_postgres_dump(artifact)
                validation_methods.add("plain_dump_completion_check")
            else:
                assert restore_tool is not None
                _validate_postgres_archive(artifact, restore_tool)
                validation_methods.add("archive_read_check")
        _write_backup_manifest(
            staging,
            backend="postgres",
            backup_format=pg_format,
            scope=scope,
            tool_name="pg_dump",
            tool_version=dump_version,
            server_version=server_version,
            validation_method="; ".join(sorted(validation_methods)),
        )
        _publish_backup(staging, target)
    except BaseException as e:
        if owned_staging:
            _remove_owned_staging(staging)
        if isinstance(e, OSError):
            raise _friendly_backup_error(e, target.parent) from e
        if isinstance(e, RuntimeError) and re.search(r"ENOSPC|No space left on device", str(e), re.IGNORECASE):
            raise RuntimeError(f"备份目标磁盘空间不足：{target.parent}") from e
        raise

    artifacts = [str(target / path.relative_to(staging)) for path in staged_artifacts]
    command = []
    if commands:
        for value in commands[-1]:
            try:
                relative = Path(value).relative_to(staging)
            except ValueError:
                command.append(value)
            else:
                command.append(str(target / relative))
    return BackupResult(
        ok=True,
        backend="postgres",
        scope=scope,
        output_dir=str(target),
        artifacts=artifacts,
        size_bytes=dir_size_bytes(target),
        message="PostgreSQL 备份完成",
        command=command,
    )


def run_mongodb_backup(
    *,
    output_parent: str | None = None,
    label: str = "",
    scope: MongoScope = "full",
    mongo_collections: list[str] | None = None,
    run_dir: Path | None = None,
) -> BackupResult:
    collections = normalize_mongo_collections(mongo_collections)
    parent = resolve_backup_parent(output_parent)
    run_dir = _validate_backup_run_dir(parent, "mongodb", run_dir)
    if not tool_on_path("mongodump"):
        raise RuntimeError(missing_tool_message("mongodump"))
    tool_version = _command_version("mongodump")
    server_version = mongo_server_info()
    host = _cfg("MONGO_HOST", "127.0.0.1")
    port = str(int(_cfg("MONGO_PORT", "27017")))
    user = _cfg("MONGO_USER", "").strip()
    password = _cfg("MONGO_PASSWORD", "")
    db_name = _cfg("MONGO_DB", "PallasBot")
    auth_source = (_cfg("MONGO_AUTH_SOURCE", "") or db_name).strip() or db_name
    staging, target, owned_staging = _begin_backup_run(parent, "mongodb", label, run_dir)
    base: list[str] = ["mongodump", "--host", f"{host}:{port}"]
    if user:
        base.extend(["--username", user])
    if password:
        base.extend(["--password", password])
        base.extend(["--authenticationDatabase", auth_source])
    commands: list[list[str]] = []
    if collections:
        for coll in collections:
            cmd = [*base, "--db", db_name, "--collection", coll, "-o", str(staging / "mongodb")]
            commands.append(cmd)
    elif scope == "important":
        for coll in _MONGO_IMPORTANT_COLLECTIONS:
            cmd = [*base, "--db", db_name, "--collection", coll, "-o", str(staging / "mongodb")]
            commands.append(cmd)
    else:
        cmd = [*base, "--db", db_name, "-o", str(staging / "mongodb")]
        commands.append(cmd)
    resolved_scope = "collections" if collections else scope
    try:
        _check_backup_target(staging)
        for cmd in commands:
            _run_checked(cmd)
        _mongo_backup_files(staging / "mongodb")
        _write_backup_manifest(
            staging,
            backend="mongodb",
            backup_format="mongodump-directory",
            scope=resolved_scope,
            tool_name="mongodump",
            tool_version=tool_version,
            server_version=server_version,
            validation_method="mongodump exit status and expected BSON structure with per-file SHA-256",
        )
        _publish_backup(staging, target)
    except BaseException as e:
        if owned_staging:
            _remove_owned_staging(staging)
        if isinstance(e, OSError):
            raise _friendly_backup_error(e, target.parent) from e
        if isinstance(e, RuntimeError) and re.search(r"ENOSPC|No space left on device", str(e), re.IGNORECASE):
            raise RuntimeError(f"备份目标磁盘空间不足：{target.parent}") from e
        raise

    published_command = []
    for value in commands[-1] if commands else []:
        try:
            relative = Path(value).relative_to(staging)
        except ValueError:
            published_command.append(value)
        else:
            published_command.append(str(target / relative))
    return BackupResult(
        ok=True,
        backend="mongodb",
        scope=resolved_scope,
        output_dir=str(target),
        artifacts=[str(target / "mongodb")],
        size_bytes=dir_size_bytes(target),
        message="MongoDB 备份完成",
        command=published_command,
    )


def run_database_backup(
    *,
    output_parent: str | None = None,
    label: str = "",
    scope: MongoScope = "full",
    pg_format: PgFormat = "custom",
    pg_tables: list[str] | None = None,
    mongo_collections: list[str] | None = None,
    run_dir: Path | None = None,
) -> BackupResult:
    backend = get_db_backend()
    if backend in ("postgres", "postgresql", "pg"):
        return run_postgres_backup(
            output_parent=output_parent,
            label=label,
            pg_format=pg_format,
            pg_tables=pg_tables,
            run_dir=run_dir,
        )
    return run_mongodb_backup(
        output_parent=output_parent,
        label=label,
        scope=scope,
        mongo_collections=mongo_collections,
        run_dir=run_dir,
    )


def assert_restorable_backup_run(target: Path, parent: Path) -> None:
    assert_deletable_backup_run(target, parent)


def _postgres_restore_env() -> dict[str, str]:
    env: dict[str, str] = {}
    password = _cfg("PG_PASSWORD", "")
    if password:
        env["PGPASSWORD"] = password
    return env


def _postgres_base_cmd() -> list[str]:
    host = _pg_host()
    port = str(int(_cfg("PG_PORT", "5432")))
    user = _cfg("PG_USER", "").strip()
    db_name = _cfg("PG_DB", "PallasBot")
    cmd = ["-h", host, "-p", port, "-d", db_name]
    if user:
        return ["-U", user, *cmd]
    return cmd


def _validate_plain_postgres_dump(path: Path) -> None:
    _assert_no_symlinks(path)
    if not path.is_file() or path.stat().st_size == 0:
        raise ValueError(f"PostgreSQL plain 备份为空或不存在：{path.name}")
    with path.open("rb") as stream:
        stream.seek(max(0, path.stat().st_size - 4096))
        trailer = stream.read()
    if b"-- PostgreSQL database dump complete" not in trailer:
        raise ValueError(f"PostgreSQL plain 备份缺少完成标记：{path.name}")


def _validate_postgres_archive(path: Path, pg_restore: Path) -> None:
    _assert_no_symlinks(path)
    if path.is_dir():
        if not (path / "toc.dat").is_file():
            raise ValueError(f"PostgreSQL directory 备份缺少 toc.dat：{path.name}")
        format_args = ["-Fd", str(path)]
    else:
        if not path.is_file() or path.stat().st_size == 0:
            raise ValueError(f"PostgreSQL archive 为空或不存在：{path.name}")
        format_args = ["-Fc", str(path)]
    _run_checked([str(pg_restore), "--file", os.devnull, *format_args])


def _command_version(command: str) -> str:
    path = shutil.which(command)
    if not path:
        raise RuntimeError(missing_tool_message(command))
    try:
        result = subprocess.run(
            [path, "--version"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as e:
        raise RuntimeError(f"读取 {command} 版本失败") from e
    if result.returncode:
        raise RuntimeError(f"读取 {command} 版本失败")
    output = (result.stdout or result.stderr).strip()
    match = re.search(r"\bversion:?\s*([0-9]+(?:\.[0-9]+)+)", output, re.IGNORECASE)
    if not match:
        match = re.search(r"\b([0-9]+(?:\.[0-9]+){1,2})\b", output)
    if not match:
        raise RuntimeError(f"无法识别 {command} 版本")
    return match.group(1)


def mongo_server_info() -> str:
    from pymongo import MongoClient

    host = _cfg("MONGO_HOST", "127.0.0.1")
    user = _cfg("MONGO_USER", "").strip()
    db_name = _cfg("MONGO_DB", "PallasBot")
    options: dict[str, Any] = {"serverSelectionTimeoutMS": 5000, "connectTimeoutMS": 3000}
    if user:
        options.update(
            username=user,
            password=_cfg("MONGO_PASSWORD", ""),
            authSource=(_cfg("MONGO_AUTH_SOURCE", "") or db_name).strip() or db_name,
        )
    client = MongoClient(host, int(_cfg("MONGO_PORT", "27017")), **options)
    try:
        return str(client.admin.command("buildInfo")["version"])
    finally:
        client.close()


def _mongo_backup_files(dump_root: Path) -> list[Path]:
    if not dump_root.is_dir():
        raise ValueError("MongoDB 备份缺少 mongodb 数据目录")
    files: list[Path] = []
    for root, dirs, names in os.walk(dump_root, followlinks=False):
        base = Path(root)
        if any((base / name).is_symlink() for name in dirs):
            raise ValueError("MongoDB 备份包含符号链接目录")
        for name in names:
            path = base / name
            if path.is_symlink() or not path.is_file():
                raise ValueError("MongoDB 备份包含不支持的文件类型")
            relative = path.relative_to(dump_root)
            if len(relative.parts) != 2 or not name.endswith((".bson", ".metadata.json")):
                raise ValueError(f"MongoDB 备份文件结构无效：{relative.as_posix()}")
            files.append(path)
    if not any(path.name.endswith(".bson") for path in files):
        raise ValueError("MongoDB 备份中未找到 BSON 集合文件")
    return files


def _has_recognized_backup_artifacts(run_dir: Path) -> bool:
    if backup_run_backend(run_dir) == "postgres":
        try:
            for artifact in _iter_postgres_restore_artifacts(run_dir):
                if artifact.is_dir() and (artifact / "toc.dat").is_file():
                    return True
                if artifact.suffix == ".sql":
                    try:
                        _validate_plain_postgres_dump(artifact)
                    except (OSError, ValueError):
                        continue
                    return True
                if artifact.is_file() and artifact.stat().st_size > 0:
                    return True
        except OSError:
            pass
        return False
    try:
        return bool(_mongo_backup_files(run_dir / "mongodb"))
    except (OSError, ValueError):
        return False


def _iter_postgres_restore_artifacts(run_dir: Path) -> list[Path]:
    artifacts: list[Path] = []
    for child in sorted(run_dir.iterdir(), key=lambda p: p.name.lower()):
        if child.is_file() and child.suffix in {".dump", ".sql"}:
            artifacts.append(child)
        elif child.is_dir() and child.name.startswith("pg_directory_"):
            artifacts.append(child)
    return artifacts


def run_postgres_restore(*, run_dir: Path) -> BackupResult:
    artifacts = _iter_postgres_restore_artifacts(run_dir)
    if not artifacts:
        raise ValueError("备份目录中未找到可复原的 PostgreSQL 产物")
    _assert_no_symlinks(run_dir)
    has_manifest = _verify_backup_manifest(run_dir)
    has_archives = any(artifact.suffix == ".dump" or artifact.is_dir() for artifact in artifacts)
    restore_tools: list[tuple[Path, str, int]] = []
    if has_archives:
        restore_tools = [
            (path, *version) for path in pg_tool_candidates("pg_restore") if (version := pg_tool_version(path))
        ]
        restore_tools.sort(key=lambda item: tuple(int(part) for part in item[1].split(".")), reverse=True)
        if not restore_tools:
            raise RuntimeError(missing_tool_message("pg_restore"))
    psql_tool: Path | None = None
    if any(artifact.suffix == ".sql" for artifact in artifacts):
        psql_tool, _version, _major = select_pg_tool("psql")

    # Check every file/archive before the first command that can modify the target database.
    artifact_restore_tools: dict[Path, Path] = {}
    for artifact in artifacts:
        if artifact.suffix == ".sql":
            if has_manifest:
                _validate_plain_postgres_dump(artifact)
            elif not artifact.is_file() or artifact.stat().st_size == 0:
                raise ValueError(f"PostgreSQL plain 备份为空或不存在：{artifact.name}")
        else:
            last_error: RuntimeError | None = None
            for restore_tool, _version, _major in restore_tools:
                try:
                    _validate_postgres_archive(artifact, restore_tool)
                except RuntimeError as e:
                    last_error = e
                    continue
                artifact_restore_tools[artifact] = restore_tool
                break
            else:
                detail = f"：{last_error}" if last_error else ""
                raise RuntimeError(f"没有可用的 pg_restore 客户端能读取归档 {artifact.name}{detail}") from last_error

    env = _postgres_restore_env()
    commands: list[list[str]] = []
    for artifact in artifacts:
        if artifact.suffix == ".sql":
            assert psql_tool is not None
            cmd = [str(psql_tool), *_postgres_base_cmd(), "-f", str(artifact)]
            _run_checked(cmd, env=env)
            commands.append(cmd)
            continue
        restore_tool = artifact_restore_tools[artifact]
        cmd = [
            str(restore_tool),
            *_postgres_base_cmd(),
            "--clean",
            "--if-exists",
            "--no-owner",
            "--no-privileges",
        ]
        if artifact.is_dir():
            cmd.extend(["-Fd", str(artifact)])
        else:
            cmd.extend(["-Fc", str(artifact)])
        _run_checked(cmd, env=env)
        commands.append(cmd)
    return BackupResult(
        ok=True,
        backend="postgres",
        scope="restore",
        output_dir=str(run_dir.resolve()),
        artifacts=[str(p) for p in artifacts],
        size_bytes=dir_size_bytes(run_dir),
        message="PostgreSQL 备份已复原",
        command=commands[-1] if commands else [],
    )


def run_mongodb_restore(*, run_dir: Path) -> BackupResult:
    if not tool_on_path("mongorestore"):
        raise RuntimeError(missing_tool_message("mongorestore"))
    dump_root = run_dir / "mongodb"
    if not dump_root.is_dir():
        raise ValueError("未找到 mongodb 备份数据目录")
    _verify_backup_manifest(run_dir)
    _mongo_backup_files(dump_root)
    host = _cfg("MONGO_HOST", "127.0.0.1")
    port = str(int(_cfg("MONGO_PORT", "27017")))
    user = _cfg("MONGO_USER", "").strip()
    password = _cfg("MONGO_PASSWORD", "")
    auth_source = (_cfg("MONGO_AUTH_SOURCE", "") or _cfg("MONGO_DB", "PallasBot")).strip()
    cmd = ["mongorestore", "--host", f"{host}:{port}", "--drop", str(dump_root)]
    if user:
        cmd.extend(["--username", user])
    if password:
        cmd.extend(["--password", password])
        cmd.extend(["--authenticationDatabase", auth_source])
    _run_checked(cmd)
    return BackupResult(
        ok=True,
        backend="mongodb",
        scope="restore",
        output_dir=str(run_dir.resolve()),
        artifacts=[str(dump_root)],
        size_bytes=dir_size_bytes(dump_root),
        message="MongoDB 备份已复原",
        command=cmd,
    )


def run_database_restore(
    path: str,
    *,
    output_parent: str | None = None,
) -> BackupResult:
    parent = resolve_backup_parent(output_parent)
    target = Path(path.strip()).resolve()
    assert_restorable_backup_run(target, parent)
    backend = backup_run_backend(target)
    if backend == "postgres":
        return run_postgres_restore(run_dir=target)
    return run_mongodb_restore(run_dir=target)


def prepare_database_backup_run_dir(
    *,
    output_parent: str | None = None,
    label: str = "",
) -> Path:
    """创建当前任务的隐藏暂存目录；成功备份后再原子发布。"""
    backend = get_db_backend()
    parent = resolve_backup_parent(output_parent)
    backend_name = "postgres" if backend in ("postgres", "postgresql", "pg") else "mongodb"
    while True:
        target = _unique_backup_target(parent, backend_name, label)
        if target.exists():
            continue
        try:
            return _new_backup_staging(target)
        except FileExistsError:
            continue
