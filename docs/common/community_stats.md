# 社区在线统计

向 [Pallas 社区中心](https://stats.pallasbot.top/) 定期上报本机**在线牛牛数量**等聚合信息，用于控制台「统计与语料」页展示全网概况，以及社区主站公开数据。

> **与共享语料无关**：在线统计默认开启；共享语料默认关闭，需单独在「语料联邦」中开启（见 [语料联邦](corpus/README.md)）。

## 你会看到什么

| 能力 | 默认 | 说明 |
| --- | --- | --- |
| 在线统计上报 | **开启** | 单进程总机向社区中心上报；分片 worker 不上报，避免重复计数 |
| 共享语料 | 关闭 | 不参与社区接话池，除非你在 WebUI 手动开启 |
| 牛牛名册公开 | 关闭 | 开启后可在社区主站气泡墙展示本部署牛牛昵称与在线状态 |

升级到新版本后，**一般无需额外配置**即可上报。若要关闭，在 WebUI **通用配置 → 语料联邦 → 在线统计与社区主站** 关闭「上报在线统计」，或在配置中设 `enabled = false`。

## 配置项

可在 `config/pallas.toml` 的 `[community_stats]` 段或 WebUI 中修改（均可省略，省略即按默认）：

| 键 | 默认 | 说明 |
| --- | --- | --- |
| `enabled` | `true` | 是否上报；设为 `false` 则完全停止 |
| `endpoint` | `https://stats.pallasbot.top/v1/heartbeat` | 上报地址；使用官方中心时通常不用改 |
| `token` | 空 | 公开中心**留空即可**；仅私有自建中心且要求鉴权时填写 |
| `interval_sec` | `300` | 上报间隔（秒），可选 60～3600 |
| `roster_public` | `false` | 是否在社区主站公开本部署牛牛名册 |

等价环境变量：`PALLAS_COMMUNITY_STATS_*`（含 `PALLAS_COMMUNITY_STATS_ROSTER_PUBLIC`）。

WebUI 路径：**通用配置 → 语料联邦 → 在线统计与社区主站**。

## 工作方式

1. 首次上报时，在 `data/pallas_config/community_stats.json` 生成本部署唯一编号（`deployment_id`）。
2. 启动约 **60 秒** 后发第一包，之后按 `interval_sec`（默认 5 分钟）周期上报。
3. `online_bots` 与控制台「在线 Bot」列表同源。
4. 主站不可用时，程序会自动尝试备站（与语料读路径相同策略）。
5. 上报失败只记日志，**不影响**牛牛启动与聊天。

### 名册公开（可选）

开启 `roster_public` 后，上报中会附带：

- 牛牛昵称、在线状态
- 近 7 日收+发消息量（用于社区主站气泡大小，不含消息正文）

社区主站 [stats.pallasbot.top](https://stats.pallasbot.top/) 气泡墙展示；**默认关闭**，随时可关。

## 控制台与 API

| 入口 | 说明 |
| --- | --- |
| **统计与语料** 页 | 只读查看全网与本部署状态 |
| **语料联邦** 配置 | 修改上报、共享语料等项 |
| `GET /pallas/api/community-stats` | 控制台拉取社区中心聚合数据 |

社区中心只读接口（供参考）：

| 路径 | 说明 |
| --- | --- |
| `GET /` | 社区主站（概览 + 牛牛气泡墙） |
| `GET /v1/stats` | 基础聚合统计 |
| `GET /v1/monitor/overview` | 一页式快照（部署 + 语料 + 版本） |
| `GET /v1/roster/bubble` | 气泡墙名册（仅 opt-in 部署） |

详见 Community-Stats 仓库 [API 文档](https://github.com/TogetsuDo/Pallas-Bot-Community-Stats/blob/main/docs/API.md)。

## 隐私说明

默认**不上报** QQ 号、群号或消息内容，只有聚合数字（在线牛数量、是否分片等）。

开启名册公开后，会上传名册内牛的 QQ、昵称、在线状态与近 7 日消息量权重；社区主站气泡墙会展示 QQ 并提供资料卡链接，便于加好友。

## 相关文档

- [语料联邦](corpus/README.md)（共享接话池，默认关闭）
- [配置存储](../architecture/settings-storage.md)
