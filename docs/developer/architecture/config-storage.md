# 配置存储

运行时配置事实源、合并顺序与读取入口。插件接法见 [配置与 WebUI](/developer/plugin-development/config-and-webui)。运维排障见 [配置参考](/maintainer/reference/config)。

## 事实源

| 路径 | 角色 | Git |
| --- | --- | --- |
| `config/pallas.example.toml` | 示例与注释 | 跟踪 |
| `config/pallas.toml` | 启动 / 基础设施（`[bootstrap]` / `[env]`） | **忽略** |
| `.env` / `.env.{ENVIRONMENT}` | 遗留只读合并；nb/pip 插件项 | 可选保留 |
| `data/pallas_config/webui.json` | 运行态最高优先级（插件页、通用段） | 随 `data/` 部署 |
| `config/pallas.webui.export.toml` | 保存时自动生成的只读 TOML 快照 | **忽略**（勿手改） |
| `local/plugins/` | 站点自有插件（`extra_plugin_dirs`） | 跟踪 `.gitkeep` |

遗留 `.env` 仍可只读合并，优先级低于 `webui.json`；WebUI 保存不再写入 `.env`。

## 合并顺序

```text
pallas.toml  →  .env / .env.{ENVIRONMENT}  →  webui.json
```

后者覆盖前者。代码不得假设某一单文件为终值。

读取：`merged_repo_settings_upper()` / `repo_env_raw_value()`（磁盘优先于 `os.environ`）。

启动：`bot.py` / `bot_hub.py` / `bot_worker.py` 在 `nonebot.init()` 前调用 `apply_repo_settings_to_environ()`，仅填充环境中尚未存在的键（保留 Docker Compose 注入）。

## 读取入口

| 场景 | API |
| --- | --- |
| 仓库合并键（平台 / 产品） | `pallas.core.foundation.config.repo_settings.repo_env_raw_value`（亦经 `pallas.api.config.repo_env_raw_value` 导出） |
| 启动灌入 environ | `apply_repo_settings_to_environ()` |
| 插件页 | `install_hot_reload_config` → `get_config()` |
| 业务侧禁止 | 散落 `os.environ` 当终值；私有「先 env 再文件」拼读 |

## 热载与分片

- 插件在 `config.py` 末尾调用 `install_hot_reload_config`；业务通过 `get_*_config()` 读取。
- Hub 控制台保存：`upsert_repo_settings_items` → `reload_plugin_config`（同进程立即生效）。
- 分片 worker 与 hub 共用 `webui.json` 时，`get()` 对比 `repo_settings_disk_revision()`（mtime），磁盘变更后自动清缓存。
- 有运行时副作用时可传 `on_reload`。

| 信号 | 含义 |
| --- | --- |
| WebUI 保存成功 | 落盘成功，不等于所有进程已更新 |
| `install_hot_reload_config` | 插件已接热载通道 |
| 启动层键 | 通常需重启进程 |
| 分片 | hub / worker 必须读同一合并结果 |

## 只读导出 TOML

每次 WebUI 保存后根据 `webui.json` 重写 `config/pallas.webui.export.toml`：

- 表名如 `[webui.plugin.repeater]`、`[webui.common.message_scrub]`
- 未识别键归入 `[webui.other]`
- **运行时仍以 `webui.json` 的 `env` 为准**

本地已有 `webui.json` 但未触发保存时：

```bash
uv run python -c "from pallas.core.foundation.config.webui_export_toml import export_webui_inspection_toml; export_webui_inspection_toml()"
```

## Docker 挂载

| 宿主机 | 容器内 |
| --- | --- |
| `pallas-bot/config/pallas.toml` | `/app/config/pallas.toml` |
| `pallas-bot/data/` | `/app/data/`（含 `pallas_config/webui.json`） |

内置 PostgreSQL 时 Compose 插值另需 `config/compose.env`（见 `config/compose.env.example`），与 `[bootstrap.postgres]` 保持一致。

## 迁移

```bash
uv run python tools/migrate_env_to_pallas.py
```

迁移后 `.env` 可保留给 nb/pip 插件；与 `webui.json` 避免同名键重复。

## 禁止

1. `os.environ[...]` 当作合并后终值
2. 插件自造私有配置文件绕开 `webui.json`
3. 平台横切项塞进单插件私有页

## 相关

- [配置与 WebUI](/developer/plugin-development/config-and-webui)
- [配置参考](/maintainer/reference/config)
- [分片运行时](shard-runtime.md)
- [站点定制与升级](/maintainer/deploy/upgrade)
