# Pallas WebUI API 契约

控制台 JSON API 由主仓 `pallas_webui` 插件提供；前端 [Pallas-Bot-WebUI](https://github.com/PallasBot/Pallas-Bot-WebUI) 通过 Axios 调用。实现源码：

- 路由注册：`src/plugins/pb_webui/extended_api.py`（`register_extended_api`）
- 轻量健康检查：`src/plugins/pb_webui/api.py`
- 登录与静态页：`src/plugins/pb_webui/public.py`

## 基址与格式

| 项 | 值 |
| --- | --- |
| 默认控制台基址 | `/pallas/` |
| API 前缀 | `/pallas/api`（与 `pallas.toml` / WebUI 配置中的 `base` 一致时为 `{base}/api`） |
| 响应信封 | `{"ok": true, "data": ...}` 或 HTTP 4xx/5xx + `detail` |
| 在线 Schema | Bot 运行时可访问 `/pallas/api/openapi.json`（仅控制台前缀下接口） |
| 离线导出 | `uv run python tools/export_pb_webui_openapi.py` → 默认生成 `openspec/pallas-console-v1.json` |

前端类型定义见 WebUI 仓库 `src/api/pallasTypes.ts`；请求封装见 `src/api/consoleApi.ts`。

## 鉴权

| 方式 | 说明 |
| --- | --- |
| 浏览器会话 | 登录后 Cookie `pallas_console_session`（`POST /pallas/api/auth/login`） |
| Header | `X-Pallas-Token: <token>`（与配置中的控制台 token 一致） |
| Query | `?token=<token>`（部分写操作兼容） |

- **读接口**：`router` 全局依赖 `_pallas_token_dep`（有效 token 或会话）
- **写接口**（PUT/POST 改配置、备份、申请处理等）：额外 `_check_pallas_write_token`（写 token 可与读 token 相同，由 `pallas_webui` 配置决定）

登录页：`GET/POST /pallas/login`（`public.py`，非 JSON API）。

## 文档分域

| 文档 | 对应 WebUI 页面 / 能力 |
| --- | --- |
| [认证与健康检查](01-auth-health.md) | 登录、health、system、bots |
| [插件与插件配置](02-plugins.md) | 插件列表、单插件 config、帮助可见性、全局禁用、舰队白名单 |
| [通用配置](03-common-config.md) | CommonConfig、cmd_perm、语料、网关探测 |
| [仪表盘与统计](04-stats-dashboard.md) | 消息统计、社区、语料热度、分片、入站调度 |
| [好友群与申请](05-social.md) | 好友/群列表、入群/好友申请 |
| [数据库](06-database.md) | 概览、备份、表行编辑 |
| [实例与账号配置](07-instances-configs.md) | instances、bot/group/user config |
| [更新与 AI 扩展](08-update-ai.md) | WebUI/Bot 更新、AI 扩展、NCM |

## 写操作与热重载

| API 域 | 落盘 | 运行时生效 |
| --- | --- | --- |
| `PUT /plugins/{name}/config` | `webui.json` `env` | `install_hot_reload_config` 插件立即 reload |
| `PUT /common-config/{section_id}` | `webui.json` | 段内字段按段逻辑 reload（cmd_perm、scrub 等） |
| `PUT /bot-configs/{account}` 等 | 数据库 | 按各 repository 约定 |
| 备份/更新 | 磁盘 / git | 可能需重启或异步任务 |

插件作者接入新配置项：见 [WebUI 插件配置](../README.md) 与 [插件 Skill · WebUI 配置](../../skills/pallas-plugin-development/references/04-webui-config.md)。

## 扩展新 API

1. 在 `extended_api.py` 的 `register_extended_api` 内增加路由（`include_in_schema=True` 便于 OpenAPI）
2. 写操作使用 `_check_pallas_write_token`
3. 在本目录补充对应域文档或新增分域文件
4. WebUI：在 `consoleApi.ts` + `pallasTypes.ts` 增加类型与请求函数

如需更新离线 schema：

```bash
uv run python tools/export_pb_webui_openapi.py
```

协议端（NapCat/Snowluma）另有独立 HTTP API，由 `pallas_protocol` 挂载，不在 `/pallas/api` 下；见 [pallas_protocol 文档](../../../plugins/pb_protocol/README.md)。
