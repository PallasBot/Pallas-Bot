# 完整部署核对

本页不再重复安装步骤。第一次启动直接看 [快速开始](quickstart.md)；源码细节看 [源码安装](install-source.md)。

生产 / VPS 上线时，按下面清单勾选验收即可。

## 验收清单

- [ ] 已按 [快速开始](quickstart.md) 或 [源码安装](install-source.md) / [Docker 部署](/maintainer/deploy/docker) 跑通 Bot
- [ ] `config/pallas.toml` 已设 `superusers` 与数据库（见 [配置从哪改](config.md)）
- [ ] 数据库可连接；启动日志无持续致命错误
- [ ] 已登录网页控制台（`http://<主机>:8088/pallas/`）
- [ ] 协议端已连 QQ，控制台显示在线（[连接 QQ](connect-qq.md)）
- [ ] 已为该牛配置 [号主](bot-owner.md)
- [ ] 测试群能收到 `牛牛帮助`

## 生产与进阶

| 主题 | 文档 |
| --- | --- |
| systemd、备份、防火墙 | [标准部署](/maintainer/deploy/deployment) |
| Docker | [Docker 部署](/maintainer/deploy/docker) |
| 配置 | [配置从哪改](config.md) · [配置要点](/maintainer/reference/config-production) |
| 多牛分片 | [分片部署](/maintainer/deploy/sharded) |
| 运维总入口 | [运维入口](/maintainer/quickstart) |

## 接下来做什么

- [命令与功能](usage.md)
- [日常管理](usage-admin.md)
- [FAQ](/deploy/faq)
