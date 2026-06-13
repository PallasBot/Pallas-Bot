# 在线统计与社区主站

公网主站：[**Pallas 社区中心**](https://stats.pallasbot.top/)（首屏为在线牛牛气泡墙，向下为全网部署概览）。

本 Bot 向社区中心定期上报**在线牛牛数量**等聚合信息，供控制台「统计与语料」与上述主站展示。

> 与**共享语料**无关：在线统计默认开启；共享语料默认关闭，见 [语料联邦](corpus/README.md)。

## 你会看到什么

| 能力 | 默认 | 说明 |
| --- | --- | --- |
| 在线统计上报 | **开启** | 单进程总机上报；分片 worker 不上报 |
| 共享语料 | 关闭 | 在语料联邦中单独开启 |
| 牛牛名册公开 | 关闭 | 社区主站气泡墙展示昵称与在线状态 |

升级后一般**无需额外配置**。要关闭：**通用配置 → 在线统计与社区主站**，或 `[community_stats] enabled = false`。

## 配置

| 键 | 默认 | 说明 |
| --- | --- | --- |
| `enabled` | `true` | 是否上报 |
| `endpoint` | 官方 heartbeat 地址 | 用官方中心时通常不改 |
| `token` | 空 | 公开中心留空 |
| `interval_sec` | `300` | 上报间隔（60～3600 秒） |
| `roster_public_qq` | `false` | 是否在主站公开牛牛 QQ |
| `roster_public_profile` | `false` | 是否在主站公开牛牛头像昵称 |

旧键 `roster_public=true` 会同时视为两项均开启。环境变量前缀：`PALLAS_COMMUNITY_STATS_*`。WebUI：**通用配置 → 在线统计与社区主站**。

## 工作方式

1. 首次上报生成 `deployment_id`，写入 `data/pallas_config/community_stats.json`。
2. 启动约 60 秒后首包，之后按间隔周期上报；`online_bots` 与控制台同源。
3. 主站不可用时自动试备站；失败只记日志，不影响聊天。
4. 开启名册相关项后随统计上报在线状态与近 7 日消息量权重（无正文）；QQ 与头像昵称可分开控制。

## 控制台与 API

| 入口 | 说明 |
| --- | --- |
| **统计与语料** | 只读全网与本部署 |
| `GET /pallas/api/community-stats` | 控制台拉聚合 |
| 社区 `GET /v1/stats` 等 | 见 [API 文档](https://github.com/TogetsuDo/Pallas-Bot-Community-Stats/blob/main/docs/API.md) |

## 隐私

默认不上报 QQ、群号或消息正文。名册公开时主站气泡墙会展示 QQ 与资料卡链接。

## 实现

[`src/features/community_stats/`](../../../src/features/community_stats/)
