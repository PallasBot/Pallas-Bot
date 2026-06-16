# 五分钟跑起来

目标：本机或 VPS 上跑起一只牛，能登录控制台、连上 QQ、在群里回一句「牛牛帮助」。

::: tip 环境要求
Python **3.12+**、[uv](https://docs.astral.sh/uv/)、MongoDB **或** PostgreSQL。协议端可等 Bot 起来后再配。
:::

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

::: details 使用 PostgreSQL
```bash
uv sync --extra pg
```
:::

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

勿将 `pallas.toml` 提交到公开仓库。更多项见 [配置要点](../Config.md)。

---

## 3. 启动

```bash
uv run nb run
```

成功标志：数据库已连接、日志出现控制台口令、`http://127.0.0.1:8088/pallas/` 可登录。

---

## 4. 连接 QQ

打开 `http://<主机>:8088/protocol/console/`，创建 NapCat 实例并扫码。

群内发 **牛牛帮助** 验收。详细说明见 [连接 QQ / 协议端](connect-qq.md)。

---

## 接下来

| 我想… | 文档 |
| --- | --- |
| 装决斗、MAA 等玩法 | [安装官方扩展](install-extensions.md) |
| 用浏览器改配置 | [Web 控制台](../common/webui/README.md) |
| VPS 长期运行 | [标准部署](../Deployment.md) |
| Docker | [Docker 部署](../DockerDeployment.md) |
| 排错 | [FAQ](../FAQ.md) |

---

## 排障速查

| 现象 | 先看 |
| --- | --- |
| 数据库连不上 | [配置要点 · MongoDB](../Config.md#mongodb) |
| 忘记控制台口令 | [FAQ](../FAQ.md) |
| 协议端连不上 | [连接 QQ](connect-qq.md) |
