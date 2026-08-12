"""Pallas-Bot WebUI console API: database routes."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

from fastapi import APIRouter, Header, HTTPException, Query
from fastapi.responses import FileResponse, JSONResponse
from nonebot import logger
from pydantic import BaseModel, ConfigDict, Field

from .console_read_cache import cached_read, drop_read_cache
from .extended_common import (
    check_pallas_write_token,
    require_pallas_token_configured,
)

if TYPE_CHECKING:
    from .config import Config


def _normalize_table_name(raw: str) -> str:
    name = (raw or "").strip().lower()
    aliases = {
        "config": "bot_config",
        "bot_config": "bot_config",
        "group_config": "group_config",
        "user_config": "user_config",
    }
    return aliases.get(name, "")


async def _get_db_table_row_public(table: str, row_id: int) -> dict[str, Any] | None:
    from pallas.core.foundation.db import (
        make_bot_config_repository,
        make_group_config_repository,
        make_user_config_repository,
    )
    from pallas.core.foundation.db.pallas_console_data import (
        bot_config_to_public,
        group_config_to_public,
        user_config_to_public,
    )

    t = _normalize_table_name(table)
    if t == "bot_config":
        repo = make_bot_config_repository()
        row = await repo.get(int(row_id), ignore_cache=True)
        return None if row is None else bot_config_to_public(row)
    if t == "group_config":
        repo = make_group_config_repository()
        row = await repo.get(int(row_id), ignore_cache=True)
        return None if row is None else group_config_to_public(row)
    if t == "user_config":
        repo = make_user_config_repository()
        row = await repo.get(int(row_id), ignore_cache=True)
        return None if row is None else user_config_to_public(row)
    raise ValueError("仅支持 config(bot_config)/group_config/user_config")


async def _upsert_db_table_row(table: str, row_id: int, data: dict[str, Any]) -> dict[str, Any]:
    from pallas.core.foundation.db import (
        make_bot_config_repository,
        make_group_config_repository,
        make_user_config_repository,
    )

    t = _normalize_table_name(table)
    payload = dict(data or {})
    if t == "bot_config":
        repo = make_bot_config_repository()
        allowed = {
            "admins",
            "disabled_plugins",
            "auto_accept_friend",
            "auto_accept_group",
            "security",
            "taken_name",
            "drunk",
            "community_roster_show_qq",
            "persona",
        }
        for k in payload:
            if k not in allowed:
                raise ValueError(f"bot_config 不允许字段: {k}")
        await repo.get_or_create(int(row_id), disabled_plugins=[])
        for k, v in payload.items():
            await repo.upsert_field(int(row_id), k, v)
        await repo.invalidate_cache()
        if "disabled_plugins" in payload:
            from packages.help.plugin_manager import apply_disabled_plugin_config_change

            await apply_disabled_plugin_config_change(
                bot_id=int(row_id),
                disabled_plugins=list(payload["disabled_plugins"] or []),
            )
        if "admins" in payload:
            from pallas.core.foundation.config.bot_admins_cache import invalidate_bot_admins_cache

            await invalidate_bot_admins_cache(int(row_id))
        got = await _get_db_table_row_public("bot_config", int(row_id))
        if got is None:
            raise ValueError("upsert 后回读失败")
        return got
    if t == "group_config":
        repo = make_group_config_repository()
        allowed = {"disabled_plugins", "roulette_mode", "banned", "sing_progress", "blocked_user_ids"}
        for k in payload:
            if k not in allowed:
                raise ValueError(f"group_config 不允许字段: {k}")
        await repo.get_or_create(int(row_id), disabled_plugins=[])
        for k, v in payload.items():
            await repo.upsert_field(int(row_id), k, v)
        await repo.invalidate_cache()
        if "blocked_user_ids" in payload:
            from packages.blacklist import apply_group_blocked_users_change

            await apply_group_blocked_users_change(int(row_id), payload["blocked_user_ids"])
        if "banned" in payload:
            from packages.blacklist import apply_group_banned_change

            await apply_group_banned_change(int(row_id), bool(payload["banned"]))
        if "disabled_plugins" in payload:
            from packages.help.plugin_manager import apply_disabled_plugin_config_change

            await apply_disabled_plugin_config_change(
                group_id=int(row_id),
                disabled_plugins=list(payload["disabled_plugins"] or []),
            )
        got = await _get_db_table_row_public("group_config", int(row_id))
        if got is None:
            raise ValueError("upsert 后回读失败")
        return got
    if t == "user_config":
        repo = make_user_config_repository()
        allowed = {"banned"}
        for k in payload:
            if k not in allowed:
                raise ValueError(f"user_config 不允许字段: {k}")
        await repo.get_or_create(int(row_id), banned=False)
        for k, v in payload.items():
            await repo.upsert_field(int(row_id), k, v)
        await repo.invalidate_cache()
        if "banned" in payload:
            from packages.blacklist import apply_user_banned_change

            await apply_user_banned_change(int(row_id), bool(payload["banned"]))
        got = await _get_db_table_row_public("user_config", int(row_id))
        if got is None:
            raise ValueError("upsert 后回读失败")
        return got
    raise ValueError("仅支持 config(bot_config)/group_config/user_config")


async def _delete_db_table_row(table: str, row_id: int) -> bool:
    from pallas.core.foundation.db import get_db_backend

    t = _normalize_table_name(table)
    if not t:
        raise ValueError("仅支持 config(bot_config)/group_config/user_config")
    backend = get_db_backend()
    if backend == "mongodb":
        from pallas.core.foundation.db.modules import BotConfigModule, GroupConfigModule, UserConfigModule

        model_map = {
            "bot_config": (BotConfigModule, "account"),
            "group_config": (GroupConfigModule, "group_id"),
            "user_config": (UserConfigModule, "user_id"),
        }
        model, key = model_map[t]
        doc = await model.find_one({key: int(row_id)})
        if doc is None:
            return False
        await doc.delete()
        return True
    if backend in ("postgres", "postgresql", "pg"):
        from sqlalchemy import delete

        from pallas.core.foundation.db.repository_pg import BotConfigRow, GroupConfigRow, UserConfigRow, get_session

        row_map = {
            "bot_config": (BotConfigRow, "account"),
            "group_config": (GroupConfigRow, "group_id"),
            "user_config": (UserConfigRow, "user_id"),
        }
        row_class, key = row_map[t]
        async with get_session() as session:
            result = await session.execute(delete(row_class).where(getattr(row_class, key) == int(row_id)))
            await session.commit()
            return bool(int(result.rowcount or 0) > 0)
    raise ValueError(f"不支持的 DB 后端: {backend}")


class _MongoAggregateBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    collection: str = Field(min_length=1, max_length=64)
    pipeline: list[Any] = Field(default_factory=list, max_length=16)


class _DbBackendPostgresBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    host: str = Field(default="127.0.0.1", max_length=255)
    port: int = Field(default=5432, ge=1, le=65535)
    user: str = Field(default="", max_length=128)
    password: str = Field(default="", max_length=512)
    db: str = Field(default="PallasBot", max_length=128)
    auto_create_db: bool = False


class _DbBackendMongoBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    host: str = Field(default="127.0.0.1", max_length=255)
    port: int = Field(default=27017, ge=1, le=65535)
    user: str = Field(default="", max_length=128)
    password: str = Field(default="", max_length=512)
    db: str = Field(default="PallasBot", max_length=128)
    auth_source: str = Field(default="", max_length=128)


class _DbBackendBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    backend: Literal["postgresql", "mongodb"]
    postgres: _DbBackendPostgresBody | None = None
    mongo: _DbBackendMongoBody | None = None
    force: bool = False


class _DbBackupBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    output_parent: str | None = Field(
        default=None,
        max_length=1024,
        description="备份父目录；空则使用仓库 backups/",
    )
    label: str = Field(default="", max_length=64, description="备份子目录名可选后缀")
    scope: Literal["full", "important"] = Field(
        default="full",
        description="MongoDB：full=整库，important=关键集合",
    )
    pg_format: Literal["custom", "plain", "directory"] = Field(
        default="custom",
        description="PostgreSQL pg_dump 格式",
    )
    pg_tables: list[str] = Field(
        default_factory=list,
        max_length=64,
        description="PostgreSQL 指定表；空则整库",
    )
    mongo_collections: list[str] = Field(
        default_factory=list,
        max_length=64,
        description="MongoDB 指定集合；空则按 scope",
    )


class _DbBackupDeleteBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    paths: list[str] = Field(min_length=1, max_length=64)
    output_parent: str | None = Field(
        default=None,
        max_length=1024,
        description="备份父目录；用于校验 paths 均在目录内",
    )


class _DbBackupRestoreBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    path: str = Field(min_length=1, max_length=2048)
    output_parent: str | None = Field(default=None, max_length=1024)


class _DbTableRowUpsertBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    table: str = Field(min_length=1, max_length=64)
    row_id: int = Field(ge=1)
    data: dict[str, Any] = Field(default_factory=dict)


class _DbMigrateMongoPgBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    dry_run: bool = False
    restart_cursor: bool = False
    switch_backend: bool = True
    try_hot_rebind: bool = True
    batch_size: int = Field(default=1000, ge=100, le=5000)
    tables: list[str] = Field(default_factory=list, max_length=32)


def register_db_router(
    router: APIRouter,
    *,
    x: str,
    plugin_config: Config,
    router_pub: APIRouter | None = None,
) -> None:
    """Register console routes."""

    from .db_lifecycle_api import register_db_lifecycle_router

    register_db_lifecycle_router(router, x=x, plugin_config=plugin_config)

    @router.get(f"{x}/db/overview", include_in_schema=True)
    async def _db_overview() -> JSONResponse:
        from pallas.core.foundation.db.pallas_console_data import database_overview

        try:
            data = await cached_read(
                key="db_overview",
                loader=database_overview,
                ttl_sec=8.0,
                stale_sec=120.0,
            )
        except Exception as e:  # noqa: BLE001
            logger.exception("[WebUI] 数据库概览失败")
            raise HTTPException(status_code=500, detail=str(e)) from e
        return JSONResponse({"ok": True, "data": data})

    @router.get(f"{x}/db/health", include_in_schema=True)
    async def _db_health() -> JSONResponse:
        from pallas.core.foundation.db.pallas_console_data import database_health_view

        try:
            data = await database_health_view()
        except Exception as e:  # noqa: BLE001
            logger.exception("[WebUI] 数据库健康探测失败")
            raise HTTPException(status_code=500, detail=str(e)) from e
        return JSONResponse({"ok": True, "data": data})

    @router.get(f"{x}/db/tables", include_in_schema=True)
    async def _db_tables() -> JSONResponse:
        from pallas.core.foundation.db.pallas_console_data import database_tables_view

        try:
            data = await cached_read(
                key="db_tables",
                loader=database_tables_view,
                ttl_sec=8.0,
                stale_sec=120.0,
            )
        except Exception as e:  # noqa: BLE001
            logger.exception("[WebUI] 数据库表列表失败")
            raise HTTPException(status_code=500, detail=str(e)) from e
        return JSONResponse({"ok": True, "data": data})

    @router.get(f"{x}/db/table-rows", include_in_schema=True)
    async def _db_table_rows(
        table: str = Query(..., description="白名单表名"),
        offset: int = Query(default=0, ge=0),
        limit: int = Query(default=50, ge=1, le=100),
    ) -> JSONResponse:
        from pallas.core.foundation.db.pallas_console_data import list_console_table_rows

        try:
            data = await list_console_table_rows(table, offset=offset, limit=limit)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e
        except Exception as e:  # noqa: BLE001
            logger.exception("[WebUI] 表分页读取失败")
            raise HTTPException(status_code=500, detail=str(e)) from e
        return JSONResponse({"ok": True, "data": data})

    @router.get(f"{x}/db/migrate/mongo-to-pg/info", include_in_schema=True)
    async def _db_migrate_mongo_pg_info() -> JSONResponse:
        from pallas.core.foundation.db.migrate_jobs import migrate_wizard_info

        try:
            data = migrate_wizard_info()
        except Exception as e:  # noqa: BLE001
            logger.exception("[WebUI] 迁移向导信息失败")
            raise HTTPException(status_code=500, detail=str(e)) from e
        return JSONResponse({"ok": True, "data": data})

    @router.post(f"{x}/db/migrate/mongo-to-pg", include_in_schema=True)
    async def _db_migrate_mongo_pg_start(
        body: _DbMigrateMongoPgBody,
        token: str | None = Query(default=None),
        x_pallas_token: str | None = Header(default=None, alias="X-Pallas-Token"),
    ) -> JSONResponse:
        check_pallas_write_token(plugin_config, x_pallas_token=x_pallas_token, token=token)
        from pallas.core.foundation.db.migrate_jobs import migrate_job_status_payload, start_migrate_job

        try:
            job = start_migrate_job(
                dry_run=body.dry_run,
                restart_cursor=body.restart_cursor,
                switch_backend=body.switch_backend,
                try_hot_rebind=body.try_hot_rebind,
                batch_size=body.batch_size,
                tables=list(body.tables),
            )
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e
        except Exception as e:  # noqa: BLE001
            logger.exception("[WebUI] 启动 Mongo→PG 迁移失败")
            raise HTTPException(status_code=500, detail=str(e)) from e
        return JSONResponse({"ok": True, "data": migrate_job_status_payload(job)})

    @router.get(f"{x}/db/migrate/mongo-to-pg/jobs/active", include_in_schema=True)
    async def _db_migrate_mongo_pg_active() -> JSONResponse:
        from pallas.core.foundation.db.migrate_jobs import active_migrate_job, migrate_job_status_payload

        job = active_migrate_job()
        return JSONResponse({"ok": True, "data": migrate_job_status_payload(job) if job else None})

    @router.get(f"{x}/db/migrate/mongo-to-pg/jobs/{{job_id}}", include_in_schema=True)
    async def _db_migrate_mongo_pg_job(job_id: str) -> JSONResponse:
        from pallas.core.foundation.db.migrate_jobs import get_migrate_job, migrate_job_status_payload

        job = get_migrate_job(job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="未找到迁移任务")
        return JSONResponse({"ok": True, "data": migrate_job_status_payload(job)})

    @router.get(f"{x}/db/backend", include_in_schema=True)
    async def _db_backend_get() -> JSONResponse:
        from pallas.core.foundation.db.backend_config import build_backend_config_view

        return JSONResponse({"ok": True, "data": build_backend_config_view()})

    @router.put(f"{x}/db/backend", include_in_schema=True)
    async def _db_backend_put(
        body: _DbBackendBody,
        token: str | None = Query(default=None),
        x_pallas_token: str | None = Header(default=None, alias="X-Pallas-Token"),
    ) -> JSONResponse:
        check_pallas_write_token(plugin_config, x_pallas_token=x_pallas_token, token=token)
        from pallas.core.foundation.db.backend_config import save_db_backend_config

        try:
            data = save_db_backend_config(body.model_dump(), force=body.force)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e
        except Exception as e:  # noqa: BLE001
            logger.exception("[WebUI] 保存数据库后端配置失败")
            raise HTTPException(status_code=500, detail=str(e)) from e
        return JSONResponse({"ok": True, "data": data})

    @router.post(f"{x}/db/backend/probe", include_in_schema=True)
    async def _db_backend_probe(
        body: _DbBackendBody,
        token: str | None = Query(default=None),
        x_pallas_token: str | None = Header(default=None, alias="X-Pallas-Token"),
    ) -> JSONResponse:
        check_pallas_write_token(plugin_config, x_pallas_token=x_pallas_token, token=token)
        from pallas.core.foundation.db.backend_config import probe_db_backend

        try:
            data = await probe_db_backend(body.model_dump())
        except Exception as e:  # noqa: BLE001
            logger.exception("[WebUI] 数据库后端探测失败")
            raise HTTPException(status_code=500, detail=str(e)) from e
        return JSONResponse({"ok": True, "data": data})

    @router.get(f"{x}/db/backup/info", include_in_schema=True)
    async def _db_backup_info() -> JSONResponse:
        from pallas.core.foundation.db.backup import backup_info

        try:
            data = backup_info()
        except Exception as e:  # noqa: BLE001
            logger.exception("[WebUI] 读取备份信息失败")
            raise HTTPException(status_code=500, detail=str(e)) from e
        return JSONResponse({"ok": True, "data": data})

    @router.post(f"{x}/db/backup", include_in_schema=True)
    async def _db_backup_run(
        body: _DbBackupBody,
        token: str | None = Query(default=None),
        x_pallas_token: str | None = Header(default=None, alias="X-Pallas-Token"),
    ) -> JSONResponse:
        """异步发起数据库逻辑备份；返回 job_id，进度见 GET /db/backup/jobs/{job_id}。"""
        check_pallas_write_token(plugin_config, x_pallas_token=x_pallas_token, token=token)
        from pallas.core.foundation.db.backup_jobs import (
            backup_job_status_payload,
            run_backup_job_sync,
            start_backup_job,
        )

        try:
            job = start_backup_job(
                output_parent=body.output_parent,
                label=body.label,
                scope=body.scope,
                pg_format=body.pg_format,
                pg_tables=body.pg_tables,
                mongo_collections=body.mongo_collections,
            )
        except RuntimeError as e:
            raise HTTPException(status_code=409, detail=str(e)) from e
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e

        job_id = job.job_id
        asyncio.create_task(asyncio.to_thread(run_backup_job_sync, job_id))
        return JSONResponse({"ok": True, "data": backup_job_status_payload(job)})

    @router.get(f"{x}/db/backup/jobs/active", include_in_schema=True)
    async def _db_backup_job_active() -> JSONResponse:
        from pallas.core.foundation.db.backup_jobs import active_backup_job, backup_job_status_payload

        job = active_backup_job()
        return JSONResponse({"ok": True, "data": backup_job_status_payload(job) if job else None})

    @router.get(f"{x}/db/backup/jobs/{{job_id}}", include_in_schema=True)
    async def _db_backup_job_status(job_id: str) -> JSONResponse:
        from pallas.core.foundation.db.backup_jobs import backup_job_status_payload, get_backup_job

        job = get_backup_job(job_id.strip())
        if job is None:
            raise HTTPException(status_code=404, detail="备份任务不存在")
        return JSONResponse({"ok": True, "data": backup_job_status_payload(job)})

    @router.get(f"{x}/db/backup/runs", include_in_schema=True)
    async def _db_backup_runs(
        output_parent: str | None = Query(default=None, max_length=1024),
    ) -> JSONResponse:
        from pallas.core.foundation.db.backup import list_backup_runs

        try:
            rows = await asyncio.to_thread(list_backup_runs, output_parent=output_parent)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e
        except Exception as e:  # noqa: BLE001
            logger.exception("[WebUI] 列举备份目录失败")
            raise HTTPException(status_code=500, detail=str(e)) from e
        return JSONResponse({"ok": True, "data": {"runs": rows}})

    @router.get(f"{x}/db/backup/browse", include_in_schema=True)
    async def _db_backup_browse(
        path: str | None = Query(default=None, max_length=1024),
    ) -> JSONResponse:
        from pallas.core.foundation.db.backup import browse_backup_directories

        try:
            data = await asyncio.to_thread(browse_backup_directories, path=path)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e
        except Exception as e:  # noqa: BLE001
            logger.exception("[WebUI] 浏览备份目录失败")
            raise HTTPException(status_code=500, detail=str(e)) from e
        return JSONResponse({"ok": True, "data": data})

    @router.post(f"{x}/db/backup/runs/restore", include_in_schema=True)
    async def _db_backup_runs_restore(
        body: _DbBackupRestoreBody,
        token: str | None = Query(default=None),
        x_pallas_token: str | None = Header(default=None, alias="X-Pallas-Token"),
    ) -> JSONResponse:
        """异步发起数据库逻辑复原；返回 job_id，进度见 GET /db/backup/jobs/{job_id}。"""
        check_pallas_write_token(plugin_config, x_pallas_token=x_pallas_token, token=token)
        from pallas.core.foundation.db.backup_jobs import (
            backup_job_status_payload,
            run_restore_job_sync,
            start_restore_job,
        )

        try:
            job = start_restore_job(path=body.path, output_parent=body.output_parent)
        except RuntimeError as e:
            raise HTTPException(status_code=409, detail=str(e)) from e
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e

        job_id = job.job_id
        asyncio.create_task(asyncio.to_thread(run_restore_job_sync, job_id))
        return JSONResponse({"ok": True, "data": backup_job_status_payload(job)})

    @router.get(f"{x}/db/backup/runs/download", include_in_schema=True)
    async def _db_backup_runs_download(
        path: str = Query(..., min_length=1, max_length=2048),
        output_parent: str | None = Query(default=None, max_length=1024),
    ) -> FileResponse:
        from pallas.core.foundation.db.backup import prepare_backup_download

        try:
            zip_path, filename = await asyncio.to_thread(
                prepare_backup_download,
                path,
                output_parent=output_parent,
            )
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e
        except Exception as e:  # noqa: BLE001
            logger.exception("[WebUI] 打包备份下载失败")
            raise HTTPException(status_code=500, detail=str(e)) from e
        return FileResponse(
            zip_path,
            filename=filename,
            media_type="application/zip",
            background=None,
        )

    @router.post(f"{x}/db/backup/runs/delete", include_in_schema=True)
    async def _db_backup_runs_delete(
        body: _DbBackupDeleteBody,
        token: str | None = Query(default=None),
        x_pallas_token: str | None = Header(default=None, alias="X-Pallas-Token"),
    ) -> JSONResponse:
        check_pallas_write_token(plugin_config, x_pallas_token=x_pallas_token, token=token)
        from pallas.core.foundation.db.backup import delete_backup_runs
        from pallas.core.foundation.db.backup_jobs import active_backup_job

        def check_active_delete_conflict() -> None:
            active = active_backup_job()
            if not active or not active.output_dir:
                return
            active_path = str(Path(active.output_dir).resolve())
            for raw in body.paths:
                if str(Path(raw.strip()).resolve()) == active_path:
                    raise HTTPException(status_code=409, detail="无法删除进行中的备份目录")

        await asyncio.to_thread(check_active_delete_conflict)

        try:
            data = await asyncio.to_thread(
                delete_backup_runs,
                body.paths,
                output_parent=body.output_parent,
            )
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e
        except Exception as e:  # noqa: BLE001
            logger.exception("[WebUI] 删除备份目录失败")
            raise HTTPException(status_code=500, detail=str(e)) from e
        return JSONResponse({"ok": True, "data": data})

    @router.post(f"{x}/db/mongodb/aggregate", include_in_schema=True)
    async def _db_mongo_aggregate(
        body: _MongoAggregateBody,
        token: str | None = Query(default=None),
        x_pallas_token: str | None = Header(default=None, alias="X-Pallas-Token"),
    ) -> JSONResponse:
        """受限 MongoDB aggregate"""
        require_pallas_token_configured(
            plugin_config,
            x_pallas_token=x_pallas_token,
            token=token,
        )
        from pallas.core.foundation.db.pallas_console_data import mongo_aggregate_console

        try:
            rows = await mongo_aggregate_console(
                collection=body.collection,
                pipeline=body.pipeline,
            )
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e
        except Exception as e:  # noqa: BLE001
            logger.exception("[WebUI] Mongo aggregate 失败")
            raise HTTPException(status_code=500, detail=str(e)) from e
        return JSONResponse({"ok": True, "data": {"rows": rows, "truncated_to": len(rows)}})

    @router.get(f"{x}/db/table-row", include_in_schema=True)
    async def _db_table_row_get(
        table: str = Query(..., description="config|bot_config|group_config|user_config"),
        row_id: int = Query(..., ge=1, description="主键值"),
    ) -> JSONResponse:
        try:
            data = await _get_db_table_row_public(table, int(row_id))
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e
        except Exception as e:  # noqa: BLE001
            logger.exception("[WebUI] 读取表行失败")
            raise HTTPException(status_code=500, detail=str(e)) from e
        if data is None:
            raise HTTPException(status_code=404, detail="未找到该行")
        return JSONResponse({"ok": True, "data": data})

    @router.put(f"{x}/db/table-row", include_in_schema=True)
    async def _db_table_row_put(
        body: _DbTableRowUpsertBody,
        token: str | None = Query(default=None),
        x_pallas_token: str | None = Header(default=None, alias="X-Pallas-Token"),
    ) -> JSONResponse:
        check_pallas_write_token(plugin_config, x_pallas_token=x_pallas_token, token=token)
        if not body.data:
            raise HTTPException(status_code=400, detail="data 为空")
        try:
            data = await _upsert_db_table_row(body.table, int(body.row_id), dict(body.data))
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e
        except Exception as e:  # noqa: BLE001
            logger.exception("[WebUI] 写入表行失败")
            raise HTTPException(status_code=500, detail=str(e)) from e
        drop_read_cache(
            ("db_overview", "bot_configs_list", "group_configs_list", "user_configs_list", "instances"),
        )
        return JSONResponse({"ok": True, "data": data})

    @router.delete(f"{x}/db/table-row", include_in_schema=True)
    async def _db_table_row_delete(
        table: str = Query(..., description="config|bot_config|group_config|user_config"),
        row_id: int = Query(..., ge=1, description="主键值"),
        token: str | None = Query(default=None),
        x_pallas_token: str | None = Header(default=None, alias="X-Pallas-Token"),
    ) -> JSONResponse:
        check_pallas_write_token(plugin_config, x_pallas_token=x_pallas_token, token=token)
        try:
            deleted = await _delete_db_table_row(table, int(row_id))
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e
        except Exception as e:  # noqa: BLE001
            logger.exception("[WebUI] 删除表行失败")
            raise HTTPException(status_code=500, detail=str(e)) from e
        drop_read_cache(
            ("db_overview", "bot_configs_list", "group_configs_list", "user_configs_list", "instances"),
        )
        if not deleted:
            raise HTTPException(status_code=404, detail="未找到该行")
        return JSONResponse({"ok": True, "data": {"deleted": True}})
