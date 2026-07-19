# 完整部署核对

[快速开始](/guide/quickstart) 的加长版：适合 VPS / 生产环境逐步勾选验收。Docker 与分片见专门文档。

## 环境要求

| 项 | 要求 |
| --- | --- |
| Python | 3.12+（推荐 `uv`） |
| 数据库 | PostgreSQL（4.0 默认）；3.x 升级可继续用 MongoDB |
| 协议端 | OneBot v11（NapCat 等，Bot 启动后再接） |
| 配置 | 从 `pallas.example.toml` 复制为 `pallas.toml` |

---

## 部署清单

- [ ] 已克隆 [Pallas-Bot](https://github.com/PallasBot/Pallas-Bot)
- [ ] 已执行 `uv sync`（PostgreSQL 驱动已在主依赖）
- [ ] 已编辑 `config/pallas.toml`（超管 QQ、数据库）
- [ ] 数据库可连接
- [ ] `uv run pallas` 无致命错误
- [ ] 已登录网页控制台
- [ ] 协议端已连 QQ，控制台显示在线
- [ ] 已为该牛配置 [号主](bot-owner.md)

---

## 步骤 1～2：代码与依赖

```bash
git clone https://github.com/PallasBot/Pallas-Bot.git
cd Pallas-Bot
uv sync
```

确认：`uv run python -c "import nonebot"` 无报错。

---

## 步骤 3：主配置

```bash
cp config/pallas.example.toml config/pallas.toml
```

至少设置 `superusers`、`db_backend`、对应数据库段。见 [配置从哪改](config.md) · [配置要点](/deploy/config#最少能跑)。

---

## 步骤 4：启动

```bash
uv run pallas
```

确认：数据库连接成功、日志有控制台口令、网页控制台可打开。

---

## 步骤 5：连接 QQ 与号主

1. [连接 QQ](connect-qq.md) — 协议端上线
2. [号主](bot-owner.md) — 配好运维人

---

## 生产与进阶

| 主题 | 文档 |
| --- | --- |
| systemd、备份、防火墙 | [标准部署](/deploy/deployment) |
| Docker | [Docker 部署](/deploy/docker) |
| 配置 | [配置从哪改](config.md) · [配置要点](/deploy/config) |
| 多牛分片 | [分片部署](/maintainer/deploy/sharded) |

---

## 下一步

- [命令与功能](/guide/usage)
- [日常管理](/guide/usage-admin)
- [FAQ](/deploy/faq)
