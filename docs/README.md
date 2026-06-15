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

## 开发

| 文档 | 说明 |
| --- | --- |
| [开发指南](develop/README.md) | 贡献者阅读顺序：环境、流程、插件与 WebUI |
| [本地开发环境](develop/environment.md) | `uv`、配置、单进程 / 分片启动 |
| [贡献与提交流程](develop/workflow.md) | Ruff、pre-commit、测试、PR 约定 |

## 社区中心

| 链接 | 说明 |
| --- | --- |
| [**Pallas 社区中心主站**](https://stats.pallasbot.top/) | 在线牛牛气泡墙、全网部署与语料概览（公开展示） |
| [在线统计与社区主站](common/community_stats.md) | 本 Bot 向中心上报在线数据、名册公开等（默认开启） |

## 架构

| 文档 | 说明 |
| --- | --- |
| [项目结构](architecture/project-structure.md) | 目录职责与分层 |
| [内核分层](architecture/common-layers.md) | `foundation` / `platform` / `features` 等 |
| [插件规范](architecture/plugin-convention.md) | `src/plugins` 组织方式 |
| [配置存储](architecture/settings-storage.md) | pallas.toml + webui.json |
| [多进程分片](architecture/bot_process_sharding.md) | hub + worker，可选生产部署 |
| [站点定制与更新](architecture/site-customization-and-updates.md) | local/plugins、更新策略 |

### 维护者附录

| 文档 | 说明 |
| --- | --- |
| [控制面与语料联邦](architecture/control-plane-corpus-federation.md) | Composite 语料、Bootstrap、OpenAPI |
| [下一世代瘦身路线图](architecture/next-gen-slimdown.md) | unified 为主的分阶段减负 |

## 插件

完整索引见 [plugins/README.md](plugins/README.md)。新增插件文档可复制 [plugins/TEMPLATE.md](plugins/TEMPLATE.md)。

## 通用能力

| 文档 | 说明 |
| --- | --- |
| [命令权限 cmd_perm](common/cmd_perm/README.md) | 帮助菜单「何人可用」 |
| [WebUI 配置热重载](common/webui/README.md) | `install_hot_reload_config` |
| [消息审查 message_scrub](common/message_scrub/README.md) | 复读/做梦入站过滤 |
| [在线统计与社区主站](common/community_stats.md) | 见上方 [社区中心](#社区中心)；上报与主站名册 |
| [语料联邦](common/corpus/README.md) | 本机 + 社区共享接话池；WebUI 配置 |

## 同步 Web 文档

主仓 `docs/` 为**权威来源**；[PallasBot/Pallas-Bot-Docs](https://github.com/PallasBot/Pallas-Bot-Docs) 的 VitePress 内容由同步脚本生成，在线站点：<https://PallasBot.github.io/Pallas-Bot-Docs/>。

### 自动同步（推荐）

向 **`main`** 或 **`docs`** 分支合并/推送且变更涉及 `docs/**` 或 `tools/scripts/sync_docs_to_web.py` 时，GitHub Actions 工作流 [`.github/workflows/sync-docs-to-web.yml`](../.github/workflows/sync-docs-to-web.yml) 会：

1. 运行 `sync_docs_to_web.py` 写入 Pallas-Bot-Docs 的 `src/`
2. 提交并 push 到 **Pallas-Bot-Docs `main`**（随后 GitHub Pages 自动部署）
3. 若 push 来自 **`main`**，尝试将 `main` 合并进本仓 **`docs`** 分支；**同一文件冲突时以 `docs` 为准**（`-X ours`），无法自动合并时跳过推送、不覆盖 `docs`

**维护者一次性配置**：在 Pallas-Bot 仓库 Actions Secrets 添加 `DOCS_SYNC_TOKEN`（PAT 需对 `PallasBot/Pallas-Bot-Docs` 有 Contents 写权限）。配置步骤见 [工作流文件](../.github/workflows/sync-docs-to-web.yml) 顶部注释。

可在 Actions 页手动 **Run workflow** 触发全量同步。

之后只需在主仓 **`docs/`** 改文档并合并到 **`main`**（或 **`docs`**），无需再手跑同步脚本。

### 本地同步

```bash
uv run python tools/scripts/sync_docs_to_web.py
```

将 Markdown 转换并写入 sibling 目录 `Pallas-Bot-Docs/src/`（路径可通过 `--dest` 指定）。
