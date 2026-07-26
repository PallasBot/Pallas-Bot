# 数据库

| 方法 | 路径 | 写 | 说明 |
| --- | --- | --- | --- |
| GET | `/db/overview` | | 表概览、行数、后端类型 |
| GET | `/db/health` | | 健康状态、原因摘要、连接池摘要 |
| GET | `/db/tables` | | 表白名单元数据与是否可分页浏览 |
| GET | `/db/table-rows` | | 白名单表分页只读（`bot_config`/`group_config`/`user_config`/`blacklist`） |
| GET | `/db/migrate/mongo-to-pg/info` | | Mongo→PG 向导元数据（表清单、schema 步骤） |
| POST | `/db/migrate/mongo-to-pg` | 是 | 异步启动迁移（可 dry-run / 切后端 / 尝试热切换） |
| GET | `/db/migrate/mongo-to-pg/jobs/active` | | 进行中迁移任务 |
| GET | `/db/migrate/mongo-to-pg/jobs/{job_id}` | | 迁移任务状态与日志 |
| GET | `/db/backend` | | 数据库后端配置（密码掩码） |
| PUT | `/db/backend` | 是 | 保存后端配置到 webui.json（需重启） |
| POST | `/db/backend/probe` | 是 | 用草稿参数探测连通性 |
| GET | `/db/backup/info` | | 备份目录与策略信息 |
| POST | `/db/backup` | 是 | 发起备份任务 |
| GET | `/db/backup/jobs/active` | | 进行中任务 |
| GET | `/db/backup/jobs/{job_id}` | | 单任务状态 |
| GET | `/db/backup/runs` | | 历史备份记录 |
| POST | `/db/backup/runs/delete` | 是 | 删除备份文件 |
| POST | `/db/mongodb/aggregate` | 是 | Mongo 聚合查询（遗留后端） |
| GET | `/db/table-row` | | 读 config 表行 |
| PUT | `/db/table-row` | 是 | 更新 bot/group/user config 行 |
| DELETE | `/db/table-row` | 是 | 删除行 |

`table` 参数限定为 `bot_config` / `group_config` / `user_config`（与控制台数据库页一致）。

备份为异步 job；大表读取有超时（WebUI 使用 `DB_HEAVY_READ_TIMEOUT_MS`）。

## 前端对应

- `DatabasePage`、`DatabaseBackupsPage`：`fetchDbOverview`、`postDbBackup`、`fetchDbBackendConfig` 等

实现：`extended_api.py` + `pallas/core/foundation/db/`；备份脚本见 `tools/scripts/`。

部署说明：[Docker 部署](/deploy/docker) 卷挂载需包含 `data/`。
