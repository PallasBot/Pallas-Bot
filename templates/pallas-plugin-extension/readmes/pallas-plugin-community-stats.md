# pallas-plugin-community-stats

Pallas-Bot 4.0 官方扩展：**社区统计心跳**与语料登记（`community_stats`）。

## 安装

需已安装 [Pallas-Bot](https://github.com/PallasBot/Pallas-Bot) **≥ 4.0**。

```bash
uv sync --extra plugins-community-stats
```

## 多进程分片

**hub / unified** 安装即可；worker **不加载**本插件（与本体 hub 白名单一致）。

## 功能说明

默认向 [stats.pallasbot.top](https://stats.pallasbot.top/) 周期上报部署心跳（匿名聚合，不含 QQ/群号/消息正文）。帮助总览默认隐藏。

关闭方式：

- WebUI **通用配置 → 在线统计与社区主站**
- 或 `config/pallas.toml`：`[community_stats] enabled = false`

首次上报生成 `deployment_id`，写入 `data/pallas_config/community_stats.json`。

同时负责控制平面 bootstrap 与社区语料登记（与 [语料](https://PallasBot.github.io/Pallas-Bot-Docs/common/corpus/) 配合）。

### 排障

| 现象 | 处理 |
| --- | --- |
| 主站看不到部署 | 确认未关闭上报；查网络与中心服务状态 |
| 分片无上报 | 确认 hub 已装本扩展 |

## 文档

| 说明 | 链接 |
| --- | --- |
| 在线统计与社区主站 | [common/community_stats](https://PallasBot.github.io/Pallas-Bot-Docs/common/community_stats) |
| 控制平面与语料 | [architecture/control-plane-corpus-federation](https://PallasBot.github.io/Pallas-Bot-Docs/architecture/control-plane-corpus-federation) |

## 源码

[`src/pallas_plugin_community_stats/`](src/pallas_plugin_community_stats/)
