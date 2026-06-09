# 配置要点（生产）

启动与长期运行前，按本节核对 **`config/pallas.toml`** 与持久化目录。完整机制见 [配置存储](architecture/settings-storage.md)。

## 配置合并顺序（优先级从低到高）

1. `config/pallas.toml` — 启动必需项（监听、超管、数据库）
2. 遗留 `.env` / `.env.{ENVIRONMENT}`（若存在）
3. `data/pallas_config/webui.json` — **WebUI 保存后最高**，覆盖同名键

生产环境建议：**启动相关、密钥、数据库** 写在 `pallas.toml`；**插件开关与业务参数** 在控制台修改并落盘 `webui.json`。

---

## 首次部署检查清单

- [ ] 已复制 `config/pallas.example.toml` → **`config/pallas.toml`**
- [ ] `[bootstrap] superusers` 已填 QQ 号
- [ ] `db_backend` 与 `[bootstrap.mongo]` / `[bootstrap.postgres]` 与实际库一致
- [ ] `host` / `port` 与防火墙、反向代理一致（默认 `0.0.0.0:8088`）
- [ ] `data/` 目录可写（首次启动自动创建子目录）
- [ ] 已记录控制台初始口令（`data/pallas_console/`，遗忘见 [FAQ](FAQ.md)）
- [ ] 未在生产环境开启 `pallas_webui_dev_mode`

---

## `[bootstrap]` 必改项

| 配置项 | 说明 | 生产注意 |
| --- | --- | --- |
| `superusers` | 超管 QQ 列表 | 至少一名可信管理员 |
| `host` / `port` | HTTP 监听 | 反代后仍常为 `0.0.0.0` + 应用端口 |
| `db_backend` | `mongodb` 或 `postgresql` | 与已安装/编排的数据库一致 |
| `access_token` | HTTP API 鉴权 | 公网或不可信网络建议设置 |

### MongoDB

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

Docker Compose 默认栈中 Bot 容器内 host 为 **`mongodb`**（由 compose 注入），见 [Docker 部署](DockerDeployment.md)。

### PostgreSQL

```toml
[bootstrap]
db_backend = "postgresql"

[bootstrap.postgres]
host = "127.0.0.1"
port = 5432
user = "postgres"
password = "your_password"
db = "PallasBot"
```

需已执行 `uv sync --extra pg`。Docker 内置 Postgres 时另备 `config/compose.env`，且 **`PG_DB` 与数据卷初始化库名一致**。

**如何确认数据库配置正确**：启动 Bot 无 `connection refused` / 认证失败；日志完成 `init_db`；控制台可打开且无持久 5xx。

---

## `[env]` 与分片（按需）

```toml
[env]
REDIS_URL = "redis://127.0.0.1:6379/0"
```

当前多进程分片跨 worker claim **依赖 Redis**；请在分片部署时配置该项，并安装 `uv sync --extra coord-redis`（或 `deploy-shard`）。`run_sharded_bot.sh` 会自动探测；与 Pallas-Bot-AI 共用同一 Redis 时填相同 URL。

---

## `[community_stats]`（可选）

默认**开启**，一般**无需**添加整段配置。关闭上报：

```toml
[community_stats]
enabled = false
```

或环境变量 `PALLAS_COMMUNITY_STATS_ENABLED=false`。详见 [社区统计](common/community_stats.md)。

---

## WebUI 与控制台

| 内容 | 存储位置 |
| --- | --- |
| 插件开关、业务配置 | `data/pallas_config/webui.json` |
| 控制台 / 协议端登录 | `data/pallas_console/auth_state.json` |
| 只读导出快照 | `config/pallas.webui.export.toml`（保存时自动生成） |

在浏览器打开 `/pallas/` 修改插件项后，**重启是否必需** 因插件而异；关键项保存后建议观察日志或按插件文档操作。

---

## 从旧 `.env` 迁移

```bash
uv run python tools/migrate_env_to_pallas.py
```

迁移后 `.env` 仍可保留 **nb/pip 插件专用** 项；与 `webui.json` **避免同名键重复**。

---

## 生产备份建议

定期备份（至少）：

- `config/pallas.toml`
- `data/pallas_config/webui.json`
- `data/pallas_console/`
- 整个 `data/`（含协议端实例、分片状态）

恢复时保持路径与挂载一致；Docker 见 [配置存储 · Docker 挂载](architecture/settings-storage.md)。

---

## 相关文档

- [配置存储](architecture/settings-storage.md) — 合并顺序、热重载
- [标准部署](Deployment.md) — 分步安装与验证
- [Docker 部署](DockerDeployment.md) — Compose 与卷挂载
- [站点定制与更新](architecture/site-customization-and-updates.md) — `local/plugins` 与更新策略
