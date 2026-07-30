# Agent Platform API

社交型 Agent 平台控制台接口：人物事实、同意、观察队列、任务、口癖与工具目录。实现：`packages/pb_webui/agent_platform_api.py`。

前端：人物 / 任务等在 **AI 观测**；工具清单与覆盖在 **AI 配置 → 接话 → 工具**。使用说明见 [AI 扩展 · 观测与策略](/guide/ai#聊得起来之后ai-观测与对话策略)。

基址与鉴权同 [WebUI API 契约](./)。写操作需写 token（`X-Pallas-Token` 或会话写权限）。

下表路径相对 `/pallas/api`。

## 总览与工具目录

| 方法 | 路径 | 写 | 说明 |
| --- | --- | --- | --- |
| GET | `/llm/agent-platform/overview` | | Query：`bot_id`、`group_id`（可选）。返回观察队列大小、工具数、任务数、口癖候选/已启用等 |
| GET | `/llm/agent-platform/tools` | | 与对话配置页工具目录同源的可调用清单与策略摘要 |

## 人物事实与同意

| 方法 | 路径 | 写 | 说明 |
| --- | --- | --- | --- |
| GET | `/llm/agent-platform/person-facts` | | Query：`bot_id`（必填）、`group_id`、`user_id`、`limit` |
| POST | `/llm/agent-platform/person-facts` | 是 | Body：`bot_id`、`user_id`、`content`；可选 `group_id`、`scope`、`source`、`confidence` |
| POST | `/llm/agent-platform/person-facts/correct` | 是 | Body：`fact_id`、`content` |
| GET | `/llm/agent-platform/consent` | | Query：`user_id`；可选 `platform`（默认 `qq`） |
| POST | `/llm/agent-platform/consent` | 是 | Body：`user_id`、`granted`；可选 `platform`、`scopes` |

## 观察队列

| 方法 | 路径 | 写 | 说明 |
| --- | --- | --- | --- |
| GET | `/llm/agent-platform/observations` | | Query：`bot_id`、`group_id`、`status`（空或 `all` 表示全部）、`limit`。`data.queue_size` 为当前队列大小 |

## 任务

| 方法 | 路径 | 写 | 说明 |
| --- | --- | --- | --- |
| GET | `/llm/agent-platform/tasks` | | Query：`group_id`（可选）、`limit` |
| POST | `/llm/agent-platform/tasks/cancel` | 是 | Body：`task_id` |

## 口癖

| 方法 | 路径 | 写 | 说明 |
| --- | --- | --- | --- |
| GET | `/llm/agent-platform/catchphrases` | | Query：`bot_id`、`status`（可选） |
| POST | `/llm/agent-platform/catchphrases/resolve` | 是 | Body：`entry_id`；`action` 为 `approve` 或 `reject` |

## 前端对应

WebUI：`src/api/agentPlatformApi.ts`；页面 `AiPeoplePage` / `AiToolsPage` / `AiTasksPage`。

离线 Schema：`openspec/pallas-console-v1.json`（`uv run python tools/sync_console_openapi.py`）。
