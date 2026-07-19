# 配置要点（生产）

启动前核对 `config/pallas.toml` 与 `data/` 持久化目录。

相关：[配置存储](/developer/architecture/config-storage) · [标准部署](/deploy/deployment) · [Docker](/deploy/docker) · [FAQ](/deploy/faq)

## 最少能跑

复制 `config/pallas.example.toml` → `config/pallas.toml`，配置 **`superusers`** 与 **`[bootstrap.postgres]`**（3.x 升级用 mongo 段）即可启动；其余在 WebUI 按需配置。

```toml
[bootstrap]
host = "0.0.0.0"
port = 8088
superusers = ["你的QQ号"]
db_backend = "postgresql"

[bootstrap.postgres]
host = "127.0.0.1"
port = 5432
user = "pallas"
password = "pallas"
db = "PallasBot"
```

启动后打开 `/pallas/`，使用日志中的默认口令登录。

## 配置合并顺序（优先级从低到高）

1. `config/pallas.toml` — 监听、超管、数据库
2. 遗留 `.env` / `.env.{ENVIRONMENT}`（若存在）
3. `data/pallas_config/webui.json` — WebUI 保存后覆盖同名键

生产建议：启动项、密钥、数据库写在 `pallas.toml`；插件开关与业务参数在控制台修改并落盘 `webui.json`。

---

## 首次部署检查清单

- [ ] 已复制 `config/pallas.example.toml` → `config/pallas.toml`
- [ ] `[bootstrap] superusers` 已填 QQ 号
- [ ] `db_backend` 与 `[bootstrap.mongo]` / `[bootstrap.postgres]` 与实际库一致
- [ ] `host` / `port` 与防火墙、反向代理一致（默认 `0.0.0.0:8088`）
- [ ] `data/` 目录可写
- [ ] 已记录控制台初始口令（`data/pallas_console/`；遗忘见 [FAQ](/deploy/faq)）
- [ ] 未在生产环境开启 `pallas_webui_dev_mode`

---

## `[bootstrap]` 必改项

| 配置项 | 说明 | 生产注意 |
| --- | --- | --- |
| `superusers` | 超管 QQ 列表 | 至少一名可信管理员 |
| `host` / `port` | HTTP 监听 | 反代后仍常为 `0.0.0.0` + 应用端口 |
| `db_backend` | `postgresql`（4.0 默认）或 `mongodb`（3.x 升级） | 与已安装数据库一致 |
| `access_token` | HTTP API 鉴权 | 公网或不可信网络建议设置 |

### PostgreSQL（4.0 默认）

```toml
[bootstrap]
db_backend = "postgresql"

[bootstrap.postgres]
host = "127.0.0.1"
port = 5432
user = "pallas"
password = "your_password"
db = "PallasBot"
# auto_create_db = true  # 可选：无库时自动 CREATE DATABASE（需 CREATEDB）
```

驱动随 `uv sync` 安装。Docker 内置 Postgres 时另备 `config/compose.env`，**`PG_DB` 与数据卷初始化库名一致**。应用账号须能连目标库并建表，不必为超级用户。扩展见 [deploy/pg/README.md](https://github.com/PallasBot/Pallas-Bot/blob/main/deploy/pg/README.md)。

### MongoDB（3.x 升级沿用）

```toml
[bootstrap]
db_backend = "mongodb"

[bootstrap.mongo]
host = "127.0.0.1"
port = 27017
user = ""
password = ""
db = "PallasBot"
```

Docker Compose 升级栈中 Bot 容器内 host 为 **`mongodb`**（compose 注入），见 [Docker 部署](/deploy/docker)。

**验证**：启动无 `connection refused` / 认证失败；日志完成 `init_db`；控制台无持久 5xx。

---

## WebUI 与控制台

| 内容 | 存储位置 |
| --- | --- |
| 插件开关、业务配置 | `data/pallas_config/webui.json` |
| 控制台 / 协议端登录 | `data/pallas_console/auth_state.json` |
| 只读导出快照 | `config/pallas.webui.export.toml`（保存时自动生成） |

浏览器修改插件项后，是否须重启因插件而异；关键项保存后观察日志或按插件文档操作。

---

## `[env]` 与分片（按需）

```toml
[env]
REDIS_URL = "redis://127.0.0.1:6379/0"
```

多进程分片跨 worker claim 依赖 Redis；分片部署时配置该项，并 `uv sync --extra coord-redis`（或 `deploy-shard`）。`run_sharded_bot.sh` 自动探测；与 Pallas-Bot-AI 共用 Redis 时填相同 URL。

## `[community_stats]`（可选）

默认开启，一般无需整段配置。关闭：

```toml
[community_stats]
enabled = false
```

或 `PALLAS_COMMUNITY_STATS_ENABLED=false`。详见 [社区统计](/common/community_stats)。

## 从旧 `.env` 迁移

```bash
uv run python tools/migrate_env_to_pallas.py
```

迁移后 `.env` 可保留 nb/pip 插件专用项；与 `webui.json` 避免同名键重复。

## 生产备份

定期备份：

- `config/pallas.toml`
- `data/pallas_config/webui.json`
- `data/pallas_console/`
- 整个 `data/`（含协议端实例、分片状态）

恢复时保持路径与挂载一致；Docker 见 [配置存储 · Docker 挂载](/developer/architecture/config-storage)。

---

## 相关文档

| 主题 | 文档 |
| --- | --- |
| 分步部署 | [标准部署](/deploy/deployment) |
| Docker 卷 | [Docker 部署](/deploy/docker) |
| 合并与热重载 | [配置存储](/developer/architecture/config-storage) |
| 站点插件 | [站点定制](/maintainer/deploy/upgrade) |
