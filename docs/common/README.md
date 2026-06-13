# 通用能力文档

跨插件共用的配置、权限与基础设施说明。结构与 [插件文档](../plugins/TEMPLATE.md) 对齐：**概述 → 配置 → 排障 → 实现**。

推荐在 WebUI **通用配置** 中修改，落盘 **`data/pallas_config/webui.json`**；主配置见 `config/pallas.toml`。

## 索引

| 文档 | 说明 |
| --- | --- |
| [命令权限](cmd_perm/README.md) | 谁可用哪些口令；帮助图动态「何人可用」 |
| [消息审查](message_scrub/README.md) | 入站过滤：复读学习、做梦采集前拦截 |
| [语料联邦](corpus/README.md) | 本机 + 社区共享接话池 |
| [社区在线统计](community_stats.md) | 向社区中心上报在线数据（默认开启） |
| [WebUI 配置热重载](webui/README.md) | 插件接入控制台、通用配置段（维护者） |

## 控制台入口对照

| 能力 | WebUI 路径 |
| --- | --- |
| 命令权限 | 通用配置 → 命令权限 |
| 联邦控制 | 通用配置 → 联邦控制 |
| 语料联邦 | 通用配置 → 语料联邦 |
| 在线统计 | 通用配置 → 在线统计与社区主站；只读见 **统计与语料** |
| 消息审查 | 通用配置 → 消息审查与入站过滤 |
| 服务网关 | 通用配置 → 外部服务地址与连通检测 |
| 插件专属项 | 通用配置各段 或 **插件** 页完整参数 |

## 相关架构

- [配置存储](../architecture/settings-storage.md)
- [控制面与语料联邦](../architecture/control-plane-corpus-federation.md)
