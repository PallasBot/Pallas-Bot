# 控制面、联邦语料与外接语料

**维护者向**：Composite 语料、Bootstrap、联邦 ingress 与中心 API 契约。部署配置见 [语料联邦](../common/corpus/README.md)。

## 现状与待做

| 能力 | 状态 |
| --- | --- |
| local + community 多读源、enroll、failover | 已交付 |
| WebUI 语料联邦、`/corpus-status` | 已交付 |
| 联邦 ingress 去重（`platform/federate` + `ingress_gate`） | 已交付 |
| `corpus_fed` 第二 PG | 待做 |
| fleet 远程快照合并 | 待做 |
| heartbeat `actions`、write_fanout 增强 | 待做 |

实现目录：`src/features/corpus/`；中心服务见 [Community-Stats](https://github.com/TogetsuDo/Pallas-Bot-Community-Stats)。

## 语料 merge

默认 `merge_order: ["local", "fed", "community"]`。

- **读**：`find_by_keywords` 按序合并；`merge_strategy` 为 `local_first` 或 `merge_counts`
- **写**：learn / upsert 始终写 local；可选异步 mirror 到 fed / community
- **ban / 清理**：仅 local

远端失败：`on_remote_failure = local_only`。

## 身份与档位

| 标识 | 说明 |
| --- | --- |
| `deployment_id` | 本地 UUID，与 community_stats 共用 |
| `tenant_id` / `federate_id` | 全量托管档位，控制面签发 |
| 自托管 | 默认库名 `PallasBot`，无需 tenant |

## 配置要点

```toml
[control_plane]
enabled = false
bootstrap_url = "https://stats.pallasbot.top/v1/bootstrap"

[corpus]
local_enabled = true
fed_enabled = "auto"
community_enabled = "auto"
merge_order = ["local", "fed", "community"]
merge_strategy = "local_first"
on_remote_failure = "local_only"
```

域名：`stats.pallasbot.top`；备案过渡期备用 `pallas.togetsudo.com`。

## 中心 API 摘要

Base：`https://stats.pallasbot.top`

| 方法 | 路径 | 用途 |
| --- | --- | --- |
| POST | `/v1/corpus/enroll` | 登记语料口令 |
| GET | `/v1/corpus/context?keywords=` | 读 Context JSON |
| POST | `/v1/corpus/contribute` | 上传短句 |
| GET | `/v1/bootstrap` | 全量托管下发 db / coord / corpus |
| POST | `/v1/heartbeat` | 扩展 `corpus` 状态与 `actions` |

`group_id: 0` 表示社区全局 anonymized 语料。`BootstrapResponse` 含 `db.business`、`db.corpus_fed`、`corpus_community`、`coord.redis_url` 等字段。

## 相关文档

- [语料联邦](../common/corpus/README.md)
- [社区统计](../common/community_stats.md)
- [多进程分片](bot_process_sharding.md)
- [配置存储](settings-storage.md)
