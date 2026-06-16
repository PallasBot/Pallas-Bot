# community_stats（社区统计上报）

> **官方扩展**：`pallas-plugin-community-stats`（`uv sync --extra plugins-community-stats`）

向社区统计中心周期上报部署心跳（在线牛牛数等聚合信息），供控制台与 [社区主站](https://stats.pallasbot.top/) 展示。**无群内用户口令**。

## 用户命令

无（维护者向后台任务）。

## 配置

WebUI **通用配置 → 在线统计与社区主站**，或 `config/stats` 段。默认开启；设置 `enabled=false` 可关闭。

详细说明见 [在线统计与社区主站](../../common/community_stats.md)。

## 实现

[`src/plugins/community_stats/`](../../../src/plugins/community_stats/)（调度在 `features/community_stats/`）
