# PostgreSQL（4.0 默认后端）

新装默认 `db_backend = "postgresql"`。Bot 启动时**只连 `PG_DB`** 建表/迁移，**不要求**超级用户或 `CREATEDB`。

## 权限期望

| 能力 | 是否需要 |
| --- | --- |
| 连接目标库 `PG_DB` | 是 |
| 在目标库 CREATE TABLE / INDEX | 是（首次启动） |
| `CREATE DATABASE` | 否（Compose 已用 `POSTGRES_DB` 建库；托管库请先建空库） |
| `CREATE EXTENSION` | 否（可选诊断） |

## 可选：自动建库

本地/无编排时，可在 `pallas.toml`：

```toml
[bootstrap.postgres]
auto_create_db = true
```

或环境变量 `PG_AUTO_CREATE_DB=true`。需要能连维护库 `postgres` 且具备 `CREATEDB`。

## 可选：pg_stat_statements

启动会在独立事务里尝试启用；失败只降级诊断，不阻断。也可由管理员手动执行：

```bash
psql "$DATABASE_URL" -f deploy/pg/extensions.sql
```

服务端还需配置 `shared_preload_libraries=pg_stat_statements`（本仓库 Compose 已带）。

## 从 MongoDB 升级

显式设 `db_backend = "mongodb"` 可继续用旧库；迁 PG 见 `tools/migrate_mongo_to_pg.py`。
