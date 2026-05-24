# Pallas-Bot 文档

> **在线阅读**：[https://PallasBot.github.io/Pallas-Bot-Docs/](https://PallasBot.github.io/Pallas-Bot-Docs/)（仓库 [PallasBot/Pallas-Bot-Docs](https://github.com/PallasBot/Pallas-Bot-Docs)）

面向部署者与插件维护者的文档索引。运行配置以 **`config/pallas.toml`** + **`data/pallas_config/webui.json`** 为主（见 [配置存储](architecture/settings-storage.md)）；遗留根目录 `.env` 只读合并，WebUI 保存不再写入 `.env`。

## 快速上手

| 文档 | 说明 |
| --- | --- |
| [配置要点](Config.md) | `pallas.toml` 与 WebUI |
| [标准部署](Deployment.md) | git clone、uv、数据库、控制台 |
| [Docker 部署](DockerDeployment.md) | Compose、卷挂载、内置 PG/Mongo |
| [常见问题](FAQ.md) | 学习机制、号主、排障 |
| [3.0 迁移](Migration-v3.md) | Mongo → PostgreSQL 等 |

## 架构

| 文档 | 说明 |
| --- | --- |
| [项目结构](architecture/project-structure.md) | 目录职责与分层 |
| [插件规范](architecture/plugin-convention.md) | `src/plugins` 组织方式 |
| [配置存储](architecture/settings-storage.md) | pallas.toml + webui.json |
| [多进程分片](architecture/bot_process_sharding.md) | hub + worker 生产部署 |
| [站点定制与更新](architecture/site-customization-and-updates.md) | local/plugins、更新策略 |

## 插件

完整索引见 [plugins/README.md](plugins/README.md)。新增插件文档可复制 [plugins/TEMPLATE.md](plugins/TEMPLATE.md)。

## 通用能力

| 文档 | 说明 |
| --- | --- |
| [命令权限 cmd_perm](common/cmd_perm/README.md) | 帮助菜单「何人可用」 |
| [WebUI 配置热重载](common/webui/README.md) | `install_hot_reload_config` |
| [消息审查 message_scrub](common/message_scrub/README.md) | 复读/做梦入站过滤 |
| [社区统计](common/community_stats.md) | 部署心跳（默认开启） |

## 同步 Web 文档

主仓 `docs/` 变更后，可在仓库根执行：

```bash
uv run python tools/scripts/sync_docs_to_web.py
```

将 Markdown 转换并写入 sibling 目录 `Pallas-Bot-Docs/src/`（路径可通过 `--dest` 指定）。
