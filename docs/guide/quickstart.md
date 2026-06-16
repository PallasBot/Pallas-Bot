# 五分钟跑起来

目标：本机或 VPS 上跑起一只牛，能登录控制台、连上 QQ、在群里回一句「牛牛帮助」。

> **环境**：Python 3.12+、[uv](https://docs.astral.sh/uv/)、MongoDB 或 PostgreSQL。协议端（NapCat）可等 Bot 起来后再配。

## 核对清单

- [ ] 克隆仓库并 `uv sync`
- [ ] 复制 `config/pallas.toml` 并填写超管 QQ、数据库
- [ ] `uv run nb run` 无报错
- [ ] 浏览器打开 `/pallas/` 并用日志口令登录
- [ ] 协议端连上 QQ，群内「牛牛帮助」有响应

---

## 1. 获取代码

```bash
git clone https://github.com/PallasBot/Pallas-Bot.git
cd Pallas-Bot
uv sync
```

用 PostgreSQL 时：`uv sync --extra pg`

---

## 2. 最少配置

```bash
cp config/pallas.example.toml config/pallas.toml
```

编辑 `config/pallas.toml`，**只改这两处**：

```toml
[bootstrap]
host = "0.0.0.0"
port = 8088
superusers = ["你的QQ号"]
db_backend = "mongodb"

[bootstrap.mongo]
host = "127.0.0.1"
port = 27017
db = "PallasBot"
```

勿将 `pallas.toml` 提交到公开仓库。

---

## 3. 启动

```bash
uv run nb run
```

成功标志：数据库已连接、日志出现控制台口令、`http://127.0.0.1:8088/pallas/` 可登录。

---

## 4. 连接 QQ

打开 `http://<主机>:8088/protocol/console/`，创建 NapCat 实例并扫码；或自管 NapCat 指向：

```text
ws://<Bot主机>:8088/onebot/v11/ws
```

群内发 **牛牛帮助** 验收。

---

## 其它部署方式

| 场景 | 文档 |
| --- | --- |
| VPS 长期运行 | [标准部署](../Deployment.md) |
| Docker | [Docker 部署](../DockerDeployment.md) |
| 多只牛 / 分片 | [多进程分片](../architecture/bot_process_sharding.md) |
| 从旧版迁移 | [3.0 迁移](../Migration-v3.md) |

## 排障

| 现象 | 先看 |
| --- | --- |
| 数据库连不上 | [配置要点 · MongoDB](../Config.md#mongodb) |
| 忘记控制台口令 | [FAQ](../FAQ.md) |
| 更多 | [FAQ](../FAQ.md) |
