# 在线统计 `pb_stats`

把本实例的在线统计同步到社区主站（心跳与聚合上报）。需要出现在社区统计、或不想上报时可在配置中关闭。旧名 `community_stats` 已内核化为本插件。

**类型**：本体 core（默认加载）

## 安装

默认加载，无需单独安装。

## 用法

无群内用户命令。后台周期性上报；控制台「统计与语料 → 社区投稿」经本链路代理社区投稿墙。社区与配置说明见 [在线统计与社区主站](../../common/community_stats.md)。

## 命令权限（代码默认）

无。

## 配置

控制台 **插件 → 在线统计（pb_stats）**，或 `config/pallas.toml` 的 `[community_stats]`。默认开启。字段见 [`packages/pb_stats/config.py`](../../../packages/pb_stats/config.py)。社区投稿由官方社区中心提供；本机无单独「投稿总开关」。

保存后（经控制台）写入 `data/pallas_config/webui.json`，并热重载上报任务。

## 排障

| 现象 | 处理 |
| --- | --- |
| 社区页看不到本实例 | 检查插件页是否关闭统计、网络是否可达；可用「统计与语料」页的连通检测 |
| 气泡墙没有某只牛 | 确认部署级名册开关，以及该牛实例配置中的「社区名册公开」 |
| 数据延迟 | 后台上报是周期性的，不会每次状态变化立刻刷新 |
| 投稿失败 / 429 | 检查到中心网络、部署级小时 / 日限额；中心是否关闭投稿墙 |

## 源码

- 插件壳：[`packages/pb_stats/`](../../../packages/pb_stats/)
- 业务逻辑：[`pallas/product/community_stats/`](../../../pallas/product/community_stats/)（含 `gallery_client.py`）

`startup.py` 启动后台上报；不响应群聊命令。

## 相关链接

- [在线统计与社区主站](../../common/community_stats.md)
- [Web 控制台 pb_webui](../pb_webui/README.md)
- 旧名指针：[community_stats.md](../community_stats.md)
