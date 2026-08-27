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
| GET | `/community-gallery` | `limit`, `mine` | 社区投稿列表（默认代理中心 `/v1/gallery/posts`；offline 时回退本部署本地留底，`mine=true` 无远端时返回本地投稿） |
| POST | `/community-gallery` | multipart | 提交投稿（正文 / 图片 / 可选 Bot；先写本地留底，再 best-effort 同步社区中心，offline 也保留本地副本） |
| DELETE | `/community-gallery/{post_id}` | | 撤下本部署投稿（本地删除 + best-effort 远端删除） |

## 前端对应

- 首页：`fetchSystem`、`fetchMessageStats`、`fetchConsoleDailyStats`、`fetchShardObservability`、`fetchIngressDispatch`
- 社区页：`fetchCommunityStats`、`fetchCommunityCorpusHot`、`fetchLocalCorpusHot`、`fetchCommunityGallery`
- 日志错误：`fetchPluginRunStats`、`postLogErrorsCleanup`

实现：`stats_dashboard_api.py`、`console_metrics_runtime.py`；社区 `pallas/product/community_stats/`、语料 `pallas/product/corpus/`、分片 `pallas/core/platform/shard/`。

架构说明：[分片运行时](../../../developer/architecture/shard-runtime.md)、[分片部署](../../../maintainer/deploy/sharded.md)。
