"""控制台 / CLI：MongoDB、PostgreSQL 逻辑备份。"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile
import zipfile
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

from pallas.core.foundation.db import get_db_backend
from pallas.core.foundation.db.__init__ import _cfg
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
    "config",
    "group_config",
    "user_config",
    "context",
)

_IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,62}$")


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
    available = tool_on_path(tool)
    restore_tool = "pg_restore" if b == "postgres" else "mongorestore"
    restore_available = tool_on_path(restore_tool)
    if b == "postgres" and not restore_available:
        restore_available = tool_on_path("psql")
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
    if proc.returncode != 0:
        err = (proc.stderr or proc.stdout or "").strip() or f"退出码 {proc.returncode}"
        cmd_hint = " ".join(cmd[:6])
        if len(cmd) > 6:
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
        if not child.is_dir() or not is_backup_run_dir(child):
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


def is_browse_allowed(path: Path) -> bool:
    resolved = path.resolve()
    project = PROJECT_ROOT.resolve()
    try:
        resolved.relative_to(project)
        return True
    except ValueError:
        pass
    try:
        project.relative_to(resolved)
        return True
    except ValueError:
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
    zip_name = f"{target.name}.zip"
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".zip")
    tmp.close()
    zip_path = Path(tmp.name)
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for root, _dirs, files in os.walk(target):
            for fn in files:
                fp = Path(root) / fn
                try:
                    arcname = fp.relative_to(target)
                except ValueError:
                    continue
                zf.write(fp, arcname)
    return zip_path, zip_name


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
    if not tool_on_path("pg_dump"):
        raise RuntimeError(missing_tool_message("pg_dump"))
    tables = normalize_pg_tables(pg_tables)
    parent = resolve_backup_parent(output_parent)
    if run_dir is None:
        run_dir = make_backup_run_dir(parent, "postgres", label=label)
    else:
        run_dir = run_dir.resolve()
        if not run_dir.is_dir():
            raise ValueError("备份输出目录不存在")
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
    artifacts: list[str] = []
    commands: list[list[str]] = []
    for table in targets:
        safe_name = re.sub(r"[^\w\-]+", "_", table) if table else safe_db
        cmd = ["pg_dump", "-h", host, "-p", port, "-d", db_name]
        if user:
            cmd.extend(["-U", user])
        if table:
            cmd.extend(["-t", table])
        if pg_format == "custom":
            artifact = run_dir / f"{safe_name}.dump"
            cmd.extend(["-Fc", "-f", str(artifact)])
        elif pg_format == "plain":
            artifact = run_dir / f"{safe_name}.sql"
            cmd.extend(["-f", str(artifact)])
        else:
            artifact = run_dir / f"pg_directory_{safe_name}"
            artifact.mkdir(parents=True, exist_ok=True)
            cmd.extend(["-Fd", "-f", str(artifact)])
        _run_checked(cmd, env=env)
        artifacts.append(str(artifact))
        commands.append(cmd)
    size = dir_size_bytes(run_dir)
    scope = "tables" if tables else pg_format
    return BackupResult(
        ok=True,
        backend="postgres",
        scope=scope,
        output_dir=str(run_dir),
        artifacts=artifacts,
        size_bytes=size,
        message="PostgreSQL 备份完成",
        command=commands[-1] if commands else [],
    )


def run_mongodb_backup(
    *,
    output_parent: str | None = None,
    label: str = "",
    scope: MongoScope = "full",
    mongo_collections: list[str] | None = None,
    run_dir: Path | None = None,
) -> BackupResult:
    if not tool_on_path("mongodump"):
        raise RuntimeError(missing_tool_message("mongodump"))
    collections = normalize_mongo_collections(mongo_collections)
    parent = resolve_backup_parent(output_parent)
    if run_dir is None:
        run_dir = make_backup_run_dir(parent, "mongodb", label=label)
    else:
        run_dir = run_dir.resolve()
        if not run_dir.is_dir():
            raise ValueError("备份输出目录不存在")
    out_root = run_dir / "mongodb"
    host = _cfg("MONGO_HOST", "127.0.0.1")
    port = str(int(_cfg("MONGO_PORT", "27017")))
    user = _cfg("MONGO_USER", "").strip()
    password = _cfg("MONGO_PASSWORD", "")
    db_name = _cfg("MONGO_DB", "PallasBot")
    auth_source = (_cfg("MONGO_AUTH_SOURCE", "") or db_name).strip() or db_name
    base: list[str] = ["mongodump", "--host", f"{host}:{port}"]
    if user:
        base.extend(["--username", user])
    if password:
        base.extend(["--password", password])
        base.extend(["--authenticationDatabase", auth_source])
    commands: list[list[str]] = []
    if collections:
        for coll in collections:
            cmd = [*base, "--db", db_name, "--collection", coll, "-o", str(out_root)]
            commands.append(cmd)
    elif scope == "important":
        for coll in _MONGO_IMPORTANT_COLLECTIONS:
            cmd = [*base, "--db", db_name, "--collection", coll, "-o", str(out_root)]
            commands.append(cmd)
    else:
        cmd = [*base, "--db", db_name, "-o", str(out_root)]
        commands.append(cmd)
    for cmd in commands:
        _run_checked(cmd)
    size = dir_size_bytes(out_root)
    resolved_scope = "collections" if collections else scope
    return BackupResult(
        ok=True,
        backend="mongodb",
        scope=resolved_scope,
        output_dir=str(run_dir),
        artifacts=[str(out_root)],
        size_bytes=size,
        message="MongoDB 备份完成",
        command=commands[-1] if commands else [],
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
    env = _postgres_restore_env()
    commands: list[list[str]] = []
    for artifact in artifacts:
        if artifact.suffix == ".sql":
            if not tool_on_path("psql"):
                raise RuntimeError(missing_tool_message("psql"))
            cmd = ["psql", *_postgres_base_cmd(), "-f", str(artifact)]
            _run_checked(cmd, env=env)
            commands.append(cmd)
            continue
        if not tool_on_path("pg_restore"):
            raise RuntimeError(missing_tool_message("pg_restore"))
        cmd = ["pg_restore", *_postgres_base_cmd(), "--clean", "--if-exists", "--no-owner", "--no-privileges"]
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
    """创建本次备份输出目录。"""
    backend = get_db_backend()
    parent = resolve_backup_parent(output_parent)
    backend_name = "postgres" if backend in ("postgres", "postgresql", "pg") else "mongodb"
    return make_backup_run_dir(parent, backend_name, label=label)
