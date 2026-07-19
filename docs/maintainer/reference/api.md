# 运维 API

维护者可直接依赖的 API 入口。

## 接口域

| 域 | 用途 |
| --- | --- |
| 认证与健康检查 | 控制台与 Bot 是否在线 |
| 插件与插件配置 | 列表、配置、治理、可见性 |
| 通用配置 | 命令权限、消息审查、服务网关等 |
| 统计与仪表盘 | 运行态、日志、分片可观测 |

## 常用路径

| 路径 | 用途 |
| --- | --- |
| `/pallas/api/health` | 健康检查 |
| `/pallas/api/system` | 控制台与系统状态 |
| `/pallas/api/bots` | Bot 在线状态 |
| `/pallas/api/plugins` | 插件 metadata 列表 |
| `/pallas/api/plugins/capabilities` | 插件能力聚合 |
| `/pallas/api/common-config/sections` | 通用配置段列表 |
| `/pallas/api/shard-observability` | 分片 worker 观测聚合 |

职责：控制台数据来源、排障观测、自动化脚本可谨慎依赖的基础运维接口。不等于主仓全部内部 FastAPI 路由都是公开契约。

## 按域

### 认证与健康检查

- 控制台是否在线
- 会话或 token 是否有效
- Bot 基础状态是否可读

典型入口：`/pallas/api/health`、`/pallas/api/system`、`/pallas/api/bots`

### 插件与治理

- 插件列表、capabilities、单插件治理状态

典型入口：`/pallas/api/plugins`、`/pallas/api/plugins/capabilities`、`/pallas/api/plugins/{plugin_name}/governance`

### 通用配置

- 配置段是否已注册
- 当前值与默认值
- 保存后是否影响运行态

典型入口：`/pallas/api/common-config/sections`、`/pallas/api/common-config/{section_id}`

### 分片与运行观测

- worker 是否在线
- 聚合状态、ingress / registry / observability 是否一致

典型入口：`/pallas/api/shard-registry`、`/pallas/api/shard-observability`、`/pallas/api/ingress-dispatch`

## 按场景

| 场景 | 路径 |
| --- | --- |
| 服务是否在线 | `/health`、`/system` |
| 插件状态 | `/plugins`、`/plugins/capabilities` |
| 分片是否正常 | `/shard-registry`、`/shard-observability`、`/ingress-dispatch` |

## 写接口

部分域提供写操作，例如：

- 插件帮助可见性
- 全局禁用
- 单插件配置
- 通用配置段

写接口是控制台治理动作的后端契约。自动化写入时：

- 优先使用文档分域已说明的接口
- 确认是否要求单独写 token
- 确认变更热生效还是需重启

## 自动化边界

| 类型 | 建议 |
| --- | --- |
| 健康检查、基础状态 | 可作为自动化入口 |
| 深层页面专用聚合 JSON | 可用于现场排障；默认不视为长期 semver 契约 |
| 长期外部集成 | 优先依赖本页列出的稳定域 |

巡检 / 监控脚本优先依赖：`health`、`system`、`bots`、`plugins`、`plugins/capabilities`、`common-config/sections`、`shard-observability`。

## 相关阅读

- [WebUI API 总览](/common/webui/api/)
- [认证与健康检查](/common/webui/api/01-auth-health)
- [插件 API](/common/webui/api/02-plugins)
- [通用配置 API](/common/webui/api/03-common-config)
- [仪表盘与统计 API](/common/webui/api/04-stats-dashboard)
