# 架构总览

这页帮助刚接触 Pallas-Bot 的开发者判断代码和能力应放在哪里，并找到下一步该读的架构文档。先理解主仓、WebUI、AI 与扩展的边界；只有要改对应领域时，再深入分片、配置或 LLM Agent。

Pallas-Bot 的可执行边界是：主仓承载运行时与产品语义；WebUI、AI、官方插件为独立协作仓；玩法能力不默认回流进 core。

## 先从这里开始

如果你的目标是：

- 写一个站点私有或社区插件，先读 [写第一个插件](/developer/plugin-development/first-plugin)，并只使用 `pallas.api.*`。
- 判断新能力是否应进入主仓，先看下面的「归属判定」，再读 [Core 与扩展](core-vs-extensions.md)。
- 修改控制台界面，到 `Pallas-Bot-WebUI` 修改前端源码；`data/pb_webui/public-react/` 是构建后的运行目录。
- 接入聊天 agent，配置独立 MaiBot 与 Pallas 桥；Pallas-Bot-AI 只承担可选媒体 runtime、队列、健康和媒体 callback，不再提供旧 RWKV 聊天入口。

统一消息入口、分片、配置存储、后台 work aux、插件治理、Agent 生命周期与输出路径都属于后续专题：当当前工作涉及这些能力时，从文末「按需深入」进入即可。

## 拓扑

![Pallas-Bot 系统拓扑：协议端、Core、WebUI、LLM Provider、扩展与可选 AI Runtime 的协作边界](/assets/architecture-system-topology.svg)

图中主仓 LLM 部分保留共享 Provider 能力；聊天 agent 已移至独立 MaiBot，现行接线以本文与 [统一消息入口](message-runtime.md) 为准。

## 层职责

| 层 | 职责 | 代码锚点 |
| --- | --- | --- |
| Core | 运行时、ingress、插件加载、cmd_perm / cooldown / help、WebUI 后端、分片、采集、MaiBot 桥与共享 Provider / 媒体能力 | `pallas/`、`packages/` |
| WebUI | 前端页面与交互；构建后同步到主仓运行目录 | 仓 `Pallas-Bot-WebUI` → `data/pb_webui/public-react/`（默认 React） |
| Chat Agent | 独立聊天决策、生成和记忆；多个 Bot 账号可共用一个运行实例与核心人设 | 独立 MaiBot；桥位于 `pallas/product/agent_bridge/` |
| AI | 可选媒体 runtime、队列、健康与媒体 callback | 仓 `Pallas-Bot-AI` |
| Official Extensions | 官方维护、可独立安装的玩法与外部能力 | 兄弟仓 / PyPI |
| Community Extensions | 第三方与站点私有能力 | Git / 本地 / 索引 |

## 归属判定

| 条件 | 归属 |
| --- | --- |
| 全站点共用的平台基础设施或产品底盘 | Core |
| 可独立发版、按需安装的玩法 / 外部集成 | Official Extension |
| 第三方、实验、站点私有 | Community / `local/plugins/` |

细则：[Core 与扩展](core-vs-extensions.md)。

## 主仓路径

| 路径 | 作用 |
| --- | --- |
| `pallas/` | 内核、平台、产品、console |
| `packages/` | 内置插件：core（`CORE_PLUGIN_NAMES`）、bundled play（`BUNDLED_PLAY_PLUGIN_NAMES`）、以及 `EXTRA_PLUGIN_PACKAGES` 对应的 extra 运行时映射；公开分发范围见 `OFFICIAL_EXTENSION_REPOS` |
| `tests/` | 内核 / 平台 / 插件 / 分片回归 |
| `docs/` | maintainer + developer 主线 |
| `local/plugins/` | 站点私有插件（不入库） |
| `data/` | 运行时数据（不入库） |

## 数据库逻辑备份

`pallas/core/foundation/db/backup.py` 与 `backup_jobs.py` 负责 CLI/WebUI 共用的 MongoDB、PostgreSQL 逻辑备份。任务先写入备份父目录内的隐藏暂存目录，通过产物检查与 SHA-256 清单后再原子发布；旧备份仍按可识别产物兼容读取。下载 ZIP 使用父目录内独立临时目录并在响应结束或中断时清理。PostgreSQL custom/directory 的 `archive_read_check`（不带 `-d` 的 `pg_restore --file` 输出到 `os.devnull`）仅为离线归档读取/解压 smoke check，不保证可复原。

## 聊天 agent 与共享模型能力

聊天 agent 由独立 MaiBot 承担，Pallas 桥按显式账号与群配置转发文本、校验回投，并保留命令优先级、权限、审核和消息采集。约 20 个账号可共用一个 MaiBot 运行实例，不需要为每个账号启动进程。桥默认关闭；未配置、断线或范围外时不会恢复自研 agent。

旧 `llm_chat` 与酒后 RWKV 聊天运行入口已退役，纯语料主动发言、Repeater 复读接话、自动表情和跟图继续保留，并沿用现有开关与桥归属抑制规则。`pallas/product/llm` 中仍保留共享 Provider、Embedding、媒体助手、配置源和显式命令工具；保留模块不代表其旧 LLM 聊天循环仍可启动。MaiBot 不会自动继承 Pallas 的工具循环、历史记忆或语义风格 Hook。

`pallas/core/platform/ai_callback/runner.py` 继续投递媒体结果；历史 `llm_chat`、`ollama`、`chat` 回调只原子领取并终止，不再发送。控制台共享模型运维仍经 `ops_api` / `runtime_api` 门面导入。接线及迁移边界见 [Agent 生命周期](agent-lifecycle.md) 与 [LLM 输出路径](llm-output-path.md)。

## 禁止假设

| 禁止 | 正确做法 |
| --- | --- |
| 把 `data/pb_webui/public-react/` 当前端源码 | 改 `Pallas-Bot-WebUI` 后同步产物 |
| 把 AI runtime 当产品语义层 | 牛格 / 语料 / 人格边界留在主仓 |
| 把 Pallas-Bot-AI 或共享 LLM 开关当聊天 agent | 聊天配置独立 MaiBot 与桥；共享 LLM 用于 Pallas 的保留能力 |
| 新玩法默认进 core | 按 [Core vs 扩展](core-vs-extensions.md) 判定 |
| 社区插件 import `pallas.core.*` | 只用 `pallas.api.*`；core 插件优先 `pallas.api`（perm/commands/limits/storage/config） |

## 按需深入

| 主题 | 文档 |
| --- | --- |
| 统一消息入口与 direct / matcher | [message-runtime.md](message-runtime.md) |
| Core 与扩展判定 | [core-vs-extensions.md](core-vs-extensions.md) |
| 分片运行时 | [shard-runtime.md](shard-runtime.md) |
| 后台任务与 work aux | [单进程部署](../../maintainer/deploy/single-process.md) |
| 配置存储 | [config-storage.md](config-storage.md) |
| 插件治理 | [plugin-governance.md](plugin-governance.md) |
| 插件业务事件日志 | [plugin-event-logging.md](plugin-event-logging.md) |
| Agent 生命周期与旧链路退役 | [agent-lifecycle.md](agent-lifecycle.md) |
| 历史内置 LLM 上下文注入 | [llm-context-injection.md](llm-context-injection.md) |
| 当前输出边界与历史 LLM 实现 | [llm-output-path.md](llm-output-path.md) |
| 群洞察与语义风格指导器 | [group-insight-semantic-style.md](group-insight-semantic-style.md) |
| 插件骨架 | [Golden Plugin](/developer/plugin-development/golden-plugin) |

入门参考：

- [仓库布局](/developer/reference/repo-layout)
- [Platform API](/developer/reference/platform-api)
- [Reload 与 Activation](/developer/plugin-development/reload-and-activation)
