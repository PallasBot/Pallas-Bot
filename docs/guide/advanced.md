# 进阶介绍

::: tip 怎么用本节
你已经能 `uv run nb run` 且群里 **牛牛帮助** 有回复，就可以按需往下翻。  
**不用从头读到尾**——当手册查就行。
:::

---

## 我想搞懂原理

| 文档 | 你会搞懂什么 |
| --- | --- |
| [理解架构](concepts.md) | 协议端、本体、库、控制台怎么串起来 |
| [配置存储](../architecture/settings-storage.md) | `pallas.toml` 和 `webui.json` 谁覆盖谁 |
| [项目结构](../architecture/project-structure.md) | 仓库里 `src/`、`data/` 各是什么 |

---

## 我要上生产 / VPS

| 文档 | 你会搞懂什么 |
| --- | --- |
| [配置要点](../Config.md) | 生产环境 `pallas.toml` 检查项 |
| [标准部署](../Deployment.md) | 分步部署、systemd、备份 |
| [Docker 部署](../DockerDeployment.md) | Compose、卷、镜像里带哪些扩展 |

数据库：**MongoDB 和 PostgreSQL 二选一**；表结构首次启动自动建，不用手搓 SQL（PG 需先建好空库）。

---

## 我要连 QQ、装插件、改配置

| 文档 | 你会搞懂什么 |
| --- | --- |
| [连接 QQ](connect-qq.md) | NapCat、WS 地址、验收口令 |
| [安装插件](install-plugins.md) | core / 官方扩展 / local 怎么装 |
| [使用指南](../user/README.md) | 控制台里常见页面去哪 |
| [Web 控制台](web-console.md) | `/pallas/` 登录与各面板说明 |

---

## 我要多只牛 / 高级玩法

| 文档 | 你会搞懂什么 |
| --- | --- |
| [多进程分片](../architecture/bot_process_sharding.md) | hub、worker、Redis |
| [站点定制](../architecture/site-customization-and-updates.md) | 更新 Bot 时不弄丢自己的插件 |
| [AI 扩展](ai.md) | Pallas-Bot-AI 怎么接 |
| [语料联邦](../common/corpus/README.md) | 跨群接话库（多数站可跳过） |

---

## 出问题了

| 文档 | 你会搞懂什么 |
| --- | --- |
| [FAQ](../FAQ.md) | 口令忘了、没反应、升级 |
| [命令权限](../common/cmd_perm/README.md) | 谁能在群里用某口令 |

---

## 我要写代码

请看 [开发指南](../develop/README.md) 和 [插件 Cookbook](../develop/plugin/cookbook.md)，不在本节展开。
