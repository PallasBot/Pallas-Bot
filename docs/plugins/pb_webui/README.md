# pb_webui（Web 控制台）

浏览器运维：实例、日志、插件配置、数据库概览等。

## 用户命令

无。入口：`http://<HOST>:<PORT>/pallas/`（维护者向）。

## 命令权限

无。

## 配置

控制台口令在 `data/pallas_console/`；前端静态资源启动时下载。详见插件 `config` 与 [FAQ · 部署排障](../../FAQ.md#部署排障)。

**统计与语料**：侧栏可查看社区与本部署状态。**社区共享接话库**、**多机协同** 等在 **通用配置** 对应分区；也可从统计页链接进入。详见 [社区共享接话库](../../common/corpus/README.md) 与 [在线统计与社区主站](../../common/community_stats.md)。

## 排障

| 现象 | 处理 |
| --- | --- |
| 无法登录 | 查启动日志初始口令 |
| 插件配置未生效 | 确认热重载插件已 `install_hot_reload_config` |

## 实现

[`src/plugins/pb_webui/`](../../../src/plugins/pb_webui/)
