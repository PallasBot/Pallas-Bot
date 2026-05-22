# 运行配置存储（pallas.toml + webui.json）

## 文件

| 路径 | 用途 | Git |
|------|------|-----|
| `config/pallas.example.toml` | 示例与注释 | 跟踪 |
| `config/pallas.toml` | 本地主配置（bootstrap、可选 `[env]`） | **忽略** |
| `data/pallas_config/webui.json` | WebUI 统一落盘（`env` 扁平键 + `sections` 按插件/通用配置分组） | 随 `data/` 部署卷 |
| `config/pallas.webui.export.toml` | **自动生成、只读**，按段带注释标题的 TOML 快照 | **忽略**（勿手改） |

遗留根目录 `.env` / `.env.{ENVIRONMENT}` 仍可**只读**合并，优先级低于 `webui.json`；WebUI 保存不再写入 `.env`。

## 合并顺序

`pallas.toml` → `webui.json` → `.env` → `.env.{ENVIRONMENT}`（后者覆盖前者）。

读取：`merged_repo_settings_upper()` / `repo_env_raw_value()`（磁盘优先于 `os.environ`）。

启动：`bot.py` / `bot_hub.py` / `bot_worker.py` 在 `nonebot.init()` 前调用 `apply_repo_settings_to_environ()`，仅填充环境中**尚未存在**的键（保留 Docker Compose 注入）。

## WebUI 热重载与分片

- 各插件在 `config.py` 末尾调用 `install_hot_reload_config`，业务代码通过 `get_*_config()` 或 `plugin_config` 代理读取。
- Hub 在控制台保存后：`upsert_repo_settings_items` → `reload_plugin_config`（同进程立即生效）。
- **分片 worker** 与 hub 共用 `data/pallas_config/webui.json` 时，`get()` 会对比 `repo_settings_disk_revision()`（文件 mtime），磁盘变更后自动清缓存，无需逐个进程调用 reload。
- 带运行时副作用的插件可传 `on_reload`（如 `repeater` 同步阈值、`help` 刷新样式缓存、`pallas_protocol` 更新 `manager._config`）。

## 只读导出 TOML（`config/pallas.webui.export.toml`）

每次 WebUI 保存（`upsert_repo_settings_items`）后，根据 `webui.json` 重写该文件：

- 表名形如 `[webui.plugin.repeater]`、`[webui.common.message_scrub]`，表上方有 `# repeater` 等标题注释
- 未识别键归入 `[webui.other]`
- 文件头注明「请勿编辑」；**运行时仍以 `webui.json` 的 `env` 为准**（`sections` 仅辅助阅读）

本地已有 `webui.json` 但未触发保存时，可执行：

```bash
uv run python -c "from src.common.config.webui_export_toml import export_webui_inspection_toml; export_webui_inspection_toml()"
```

## Docker 挂载

| 宿主机 | 容器内 |
|--------|--------|
| `pallas-bot/config/pallas.toml` | `/app/config/pallas.toml` |
| `pallas-bot/data/` | `/app/data/`（含 `pallas_config/webui.json`） |

内置 PostgreSQL 时 Compose 插值另需 `pallas-bot/config/compose.env`（见 [`config/compose.env.example`](../../config/compose.env.example)），与 `pallas.toml` 中 `[bootstrap.postgres]` 保持一致。

## 迁移

```bash
uv run python tools/migrate_env_to_pallas.py
```

迁移后请检查根目录是否仍保留旧 **`.env`**：合并顺序中 `.env` **晚于** `webui.json`，残留同名键会导致 WebUI 保存不生效。可删除已迁入 `pallas.toml` / `webui.json` 的项，或整份备份后移除 `.env`。

## 实现

- `src/common/config/repo_settings.py` — 读写与合并
- `src/common/config/dotenv.py` — 兼容导出
