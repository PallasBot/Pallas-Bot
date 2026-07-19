---
name: pallas-plugin-development
description: >
  当用户要求「写 Pallas 插件」「给插件加命令」「cmd_perm 怎么接」「WebUI 热重载配置」
  「on_command 还是 on_message」「local/plugins 怎么覆盖」「帮助图 menu_data 怎么写」
  「message_scrub 要不要接」「插件放哪、路径 helper 用什么」时，优先读取本 SKILL。
  面向 Pallas-Bot 主仓与 local/plugins 站点插件开发；Agent 应按章节按需加载 references，勿一次性读完全部。
---

# Pallas 插件开发指南（Agent 入口）

> 本 Skill **描述 Pallas-Bot 仓库约定**（内核分层、cmd_perm、WebUI、多牛分片等）
> 章节拆在 `references/`；需要某专题时再读对应文件，**不要**把全部 references 塞进上下文。
> 人类贡献者请从 [Cookbook · 牛牛赞我](../../developer/plugin-development/getting-started.md) 先进入现行主线；速查见 [getting-started.md](../../developer/plugin-development/getting-started.md)。

## 章节索引

| 章节 | 主题 | 文件 |
| --- | --- | --- |
| 一 | 插件基础（目录、入口、公开 API、主仓 vs local） | [references/01-plugin-basics.md](./references/01-plugin-basics.md) |
| 二 | Matcher 决策树（on_command / on_message / 事件） | [references/02-matchers-decision.md](./references/02-matchers-decision.md) |
| 三 | cmd_perm 与帮助文案 | [references/03-cmd-perm-and-help.md](./references/03-cmd-perm-and-help.md) |
| 四 | WebUI 配置热重载 | [references/04-webui-config.md](./references/04-webui-config.md) |
| 五 | 路径、数据与资源 | [references/05-paths-and-data.md](./references/05-paths-and-data.md) |
| 六 | message_scrub 入站过滤 | [references/06-message-scrub.md](./references/06-message-scrub.md) |
| 七 | 测试与文档自检 | [references/07-tests-and-docs.md](./references/07-tests-and-docs.md) |
| 八 | 完整示例插件 checklist | [references/08-golden-plugin-checklist.md](./references/08-golden-plugin-checklist.md) |

## 推荐流程

1. **新建插件** → [一、插件基础](./references/01-plugin-basics.md)
2. **选触发方式** → [二、Matcher 决策树](./references/02-matchers-decision.md)
3. **命令权限与帮助** → [三、cmd_perm](./references/03-cmd-perm-and-help.md)
4. **控制台可改配置** → [四、WebUI 热重载](./references/04-webui-config.md)
5. **复读/做梦类入站** → [六、message_scrub](./references/06-message-scrub.md)
6. **提交前** → [八、checklist](./references/08-golden-plugin-checklist.md)

## 关键概念速记

- **技术栈**：NoneBot2 + OneBot v11；配置 `pallas.toml` + `webui.json`；控制台为 Pallas WebUI（`/pallas/`）。
- **插件位置**：上游 `packages/<name>/`；站点定制 `local/plugins/<name>/`（同名时 **local 优先**，需 `extra_plugin_dirs` + 重启）。
- **多牛舰队**（进阶）：入站调度、进程分片见 [分片运行时](../../developer/architecture/shard-runtime.md)、[分片部署](../../maintainer/deploy/sharded.md)。
- **导入分层**：社区插件仅 `pallas.api.*`；内置插件可用 `pallas.api.*` + `pallas.product.*`；跨插件能力不要深层 import 内核内部文件。见 [一、公开 API](./references/01-plugin-basics.md)。
- **命令 ID**：`{插件}.{动作}` 须在 metadata、`permission_for_command`、matcher 中**完全一致**。
- **plugin_sdk**：口令型优先 `message_command` + `bind_alias_handlers`（见 [Golden Plugin](../../developer/plugin-development/golden-plugin.md)）。
- **core 插件**：`CORE_PLUGIN_NAMES` 默认加载；维护者向包名 `pb_*`；golden 模板见 [八、checklist](./references/08-golden-plugin-checklist.md)。
- **reload_policy**：改 help/ingress 声明且不想重启时设 `metadata`（见 [Reload 与 Activation](../../developer/plugin-development/reload-and-activation.md)）。
- **帮助文案**：`usage` 不写死权限；`trigger_condition` 只写怎么说；权限绑 `command_permission` + WebUI 矩阵。
- **配置读取**：WebUI 可调项用 `get_config()` / `get_my_config()`，**勿**在模块顶层缓存配置快照。
- **日志**：loguru 风格，占位用 `{}` 或 f-string，避免 `"%s"` 传统 logging 写法。

## 权威文档（仓库内）

| 文档 | 用途 |
| --- | --- |
| [plugin-development/getting-started.md](../../developer/plugin-development/getting-started.md) | 人类向现行入口 |
| [plugin-development/golden-plugin.md](../../developer/plugin-development/golden-plugin.md) | 目录与骨架 |
| [plugin-development/config-and-webui.md](../../developer/plugin-development/config-and-webui.md) | 配置与 WebUI |
| [cmd_perm/README.md](../../common/cmd_perm/README.md) | 权限与 menu 细则 |
| [webui/README.md](../../common/webui/README.md) | 热重载配置 |
| [AGENTS.md](../../../AGENTS.md) | Agent / CI 协作约定 |
