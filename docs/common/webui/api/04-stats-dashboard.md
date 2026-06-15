# 仪表盘与统计

## 系统与分片

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/shard-registry` | 分片注册表、rebalance 提示 |
| GET | `/shard-observability` | 分片 worker 观测聚合 |
| GET | `/ingress-dispatch` | 中央入站调度指标（lane、matcher 预激活等） |

## 消息与控制台统计

| 方法 | 路径 | Query | 说明 |
| --- | --- | --- | --- |
| GET | `/message-stats` | `self_id?` | 收/发消息、API 调用历史等 |
| GET | `/console-daily-stats` | | 控制台日统计（插件运行、matcher 等） |
| GET | `/plugin-run-stats` | | Matcher 错误与运行统计（日志错误页） |
| POST | `/log-errors/cleanup` | 是 | 清理已展示的错误日志缓冲 |

## 社区与语料

| 方法 | 路径 | Query | 说明 |
| --- | --- | --- | --- |
| GET | `/community-stats` | | 社区中心公开统计快照 |
| GET | `/community-corpus-hot` | `period`, `tab`, `mode` | 社区语料热度 |
| GET | `/local-corpus-hot` | 同上 | 本机语料热度 |
| GET | `/corpus-status` | | 语料联邦状态 |
| GET | `/federation-onboarding` | | 联邦接入引导信息 |

## 前端对应

- 首页：`fetchSystem`、`fetchMessageStats`、`fetchConsoleDailyStats`、`fetchShardObservability`、`fetchIngressDispatch`
- 社区页：`fetchCommunityStats`、`fetchCommunityCorpusHot`、`fetchLocalCorpusHot`
- 日志错误：`fetchPluginRunStats`、`postLogErrorsCleanup`

实现：`extended_api.py`；社区 `src/features/community_stats/`、语料 `src/features/corpus/`、分片 `src/platform/shard/`。

架构说明：[中央入站调度](../../../architecture/central-ingress-dispatch.md)、[多进程分片](../../../architecture/bot_process_sharding.md)。
