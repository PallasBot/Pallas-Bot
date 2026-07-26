# 在线统计与社区主站

公网主站：[**Pallas 社区中心**](https://stats.pallasbot.top/)（首屏为在线牛牛气泡墙，向下为部署概览、语料热词与**社区投稿墙**）。

本 Bot 通过 core 插件 **`pb_stats`** 向社区中心定期上报在线牛数量等聚合信息，供控制台「统计与语料」与上述主站展示。升级后一般**无需额外配置**；要关闭上报或调整名册公开时，打开 **插件 → 在线统计（pb_stats）**。

> 与**社区共享接话库**无关：在线统计默认开启；共享语料默认关闭，见 [语料联邦](/common/corpus)。

## 你会看到什么

| 能力 | 默认 | 说明 |
| --- | --- | --- |
| 在线统计上报 | **开启** | 单进程 / hub 上报；分片 worker 不上报 |
| 共享语料 | 关闭 | 在语料联邦中单独开启 |
| 牛牛名册公开 | **头像昵称开启**（QQ 默认关） | 主站气泡墙展示昵称与在线状态；QQ / 资料卡链接可另开 |
| 语料热词 | 主站默认高频池 | 日 / 周 / 月窗口；机群叠加见 `mode=fleet` |
| 社区投稿墙 | 中心默认开启 | 主站轮换展示文字 / 截图；在控制台「统计与语料 → 社区投稿」提交 |

也可在 `pallas.toml` 设 `[community_stats] enabled = false`。

## 社区投稿墙

主站分区 **「社区投稿」**（锚点 `#gallery`）：纯文字以模拟发言卡轮换；带图且未绑 Bot 身份的投稿直接展示截图。

| 入口 | 说明 |
| --- | --- |
| **统计与语料 → 社区投稿** | 本机提交 / 查看 / 撤下本部署投稿（经 Bot 代理中心 API） |
| 主站 `#gallery` | 公开展示已发布投稿（只读） |

投稿规则摘要：

- 正文最多 500 字；图片可选（jpeg / png / webp / gif，约 ≤3MB）；正文与图片至少其一。
- 可选绑定 Bot 账号（带头像昵称，主站渲染发言卡）；不指定账号的带图投稿按截图瓦片展示。
- 按部署限流（中心默认约每小时 30、每日 10；以中心配置为准）。
- 截图可能含群名或 QQ，**提交即公开展示**；仅本部署可撤下自己的投稿。

中心侧路径：`/v1/gallery/posts`（列表 / 创建）、`DELETE /v1/gallery/posts/{id}`、图片 `GET /v1/gallery/images/{id}`。Bot 控制台代理：`/pallas/api/community-gallery`。详见 [Community-Stats API](https://github.com/TogetsuDo/Pallas-Bot-Community-Stats/blob/main/docs/API.md)。

## 配置

| 键 | 默认 | 说明 |
| --- | --- | --- |
| `enabled` | `true` | 是否上报 |
| `endpoint` | `https://stats.pallasbot.top/v1/heartbeat` | 用官方中心时通常不改；主站不可用时会自动试备站 |
| `token` | 空 | 公开中心留空；仅中心配置了 `HEARTBEAT_TOKEN` 时再填 |
| `interval_sec` | `300` | 上报间隔（可选 60～3600 秒） |
| `roster_public_qq` | `false` | 是否在主站公开牛牛 QQ / 资料卡链接 |
| `roster_public_profile` | `true` | 是否在主站公开牛牛头像与昵称 |
| `corpus_hot_snapshot_interval_sec` | `900` | 心跳附带本机热词快照的最小间隔（秒） |

旧键 `roster_public=true`（或环境变量 `PALLAS_COMMUNITY_STATS_ROSTER_PUBLIC`）会同时视为 QQ 与头像昵称两项均开启。环境变量前缀：`PALLAS_COMMUNITY_STATS_*`。

**WebUI 入口**：

| 入口 | 作用 |
| --- | --- |
| **插件 → 在线统计（pb_stats）** | 上报开关、间隔、名册公开（权威配置页） |
| **统计与语料** | 只读全网与本部署；**社区投稿**分区；可跳转到上述插件页 |
| **实例与连接 → 某只牛** | 「社区名册公开」：关闭后该牛不进入气泡墙名册 |

旧路径「通用配置 → 在线统计」与 `/community-stats-config` 会重定向到插件页。配置段 ID 在落盘 / 兼容层仍可能写作 `community_stats`。

## 工作方式

1. 首次上报生成 `deployment_id`，写入 `data/pallas_config/community_stats.json`。
2. 启动约 60 秒后首包，之后按间隔周期上报；`online_bots` 与控制台同源。
3. 主站不可用时自动试备站；失败只记日志，不影响聊天。
4. 开启名册相关项后随统计上报在线状态与近 7 日消息量权重（无正文）；部署级可分开控制 QQ 与头像昵称，实例级可单独退出名册。
5. 若本机开启了共享语料贡献，心跳可按间隔附带本机热词快照（供主站 `mode=fleet`）。
6. 社区投稿经控制台代理写中心；列表可按本 `deployment_id` 筛选「我的投稿」。

## 控制台与 API

| 入口 | 说明 |
| --- | --- |
| **统计与语料** | 只读全网与本部署；含社区投稿 |
| `GET /pallas/api/community-stats` | 控制台拉聚合 |
| `GET` / `POST` / `DELETE` `/pallas/api/community-gallery` | 社区投稿代理 |
| `POST /pallas/api/community-stats/connectivity-check` | 本机到社区中心的连通诊断 |
| 社区 `GET /v1/stats`、`GET /v1/roster/bubble`、`/v1/gallery/*` 等 | 见 [Community-Stats API](https://github.com/TogetsuDo/Pallas-Bot-Community-Stats/blob/main/docs/API.md) |

## 隐私

默认上报昵称与头像；QQ 与资料卡链接默认不公开。心跳不上报群号或消息正文。开启 QQ 公开后，主站气泡可唤起资料卡。单只牛可在实例配置中退出名册。

社区投稿为**主动公开展示**：正文与上传图片会进入主站投稿墙；请勿提交含敏感信息的截图。

## 实现

- 插件壳：[`packages/pb_stats/`](https://github.com/PallasBot/Pallas-Bot/tree/main/packages/pb_stats/)
- 业务：[`pallas/product/community_stats/`](https://github.com/PallasBot/Pallas-Bot/tree/main/pallas/product/community_stats/)（含 `gallery_client.py`）
- 社区中心仓：[Pallas-Bot-Community-Stats](https://github.com/TogetsuDo/Pallas-Bot-Community-Stats)

## 后续阅读

- [语料联邦](/common/corpus)
- [插件说明 pb_stats](/plugins/pb_stats)
- [WebUI API · 仪表盘与统计](/common/webui/api/04-stats-dashboard)
