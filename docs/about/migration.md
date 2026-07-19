# 2.x → 3.0 数据迁移（归档）

> 从 **3.x 升到 4.0** 请看 [从 3.x 迁到 4.0](/guide/4.0-migration)。本页仅保留 2.x → 3.0（MongoDB → PostgreSQL）步骤。

> 导航：[`README`](https://github.com/PallasBot/Pallas-Bot/blob/main/README.md) · [`标准部署`](/deploy/deployment) · [`Docker 部署`](/deploy/docker) · [`FAQ`](/deploy/faq)

## 适用范围

- 适用于已有历史数据、准备升级到 `3.0` 的实例。
- 核心变化：`3.0` 引入 `pallas_protocol` 与 `pallas_webui`，并支持 PostgreSQL 数据后端。

## 升级前检查

1. 停止 Bot 写入流量（避免迁移期间源数据持续变化）。
2. 备份 MongoDB（至少包含业务库）。
3. 准备 PostgreSQL 空库，并确保账号具备建表与写入权限。
4. 确认 `config/pallas.toml` 中连接信息可用（`[bootstrap]` / `[bootstrap.mongo]` / `[bootstrap.postgres]`），或从旧 `.env` 运行 `tools/migrate_env_to_pallas.py`。

## 依赖安装

```bash
uv sync
```

## 迁移命令

### 全量迁移

```bash
uv run python tools/migrate_mongo_to_pg.py
```

### 指定库名

```bash
uv run python tools/migrate_mongo_to_pg.py --pg-db MyBot --mongo-db PallasBot
```

### 仅迁移部分表

```bash
uv run python tools/migrate_mongo_to_pg.py --tables context message --batch 500
```

### 仅演练（不写入目标库）

```bash
uv run python tools/migrate_mongo_to_pg.py --dry-run
```

## 验证清单

迁移完成后，建议至少确认以下内容：

1. 脚本输出汇总中 `failed` 为 `0` 或可解释范围。
2. 核心业务表行数与预期一致（`context`、`message`、`botconfig`、`groupconfig`、`userconfig`）。
3. 启动 Bot 后基础功能可用（复读、配置读取、实例状态查询）。
4. WebUI 页面可正常加载，数据库概览接口可返回。

## 回滚方案

如迁移后发现异常，可按以下顺序回退：

1. 停止 3.0 实例。
2. 保留 PostgreSQL 现场数据用于排查。
3. 恢复到升级前代码与 MongoDB 备份。
4. 回退后先执行功能自检，再恢复对外流量。

## 已知事项

- 迁移脚本支持断点续跑。
- `--restart` 当前仅清空迁移状态表（`pallas_migration_state`），不会自动清空目标业务表。
- 若目标库已有历史数据，重复执行迁移前请先确认策略（避免非幂等场景下重复写入）。

## 建议流程

1. 测试环境先完整跑通迁移与回归。
2. 生产环境按“停写 -> 迁移 -> 验证 -> 切换”的顺序执行。
3. 切换后观察一段时间，再做历史环境清理。
