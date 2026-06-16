# 五分钟跑起来

::: tip 读完你能做什么
本机跑起一只牛 → 登录网页控制台 → 连上 QQ → 群里发 **牛牛帮助** 有回复。
:::

## 你需要准备

| 项 | 要求 |
| --- | --- |
| Python | **3.12+**（推荐用 [uv](https://docs.astral.sh/uv/) 管理） |
| 数据库 | **MongoDB** 或 **PostgreSQL** 二选一，本机或 Docker 起一个即可 |
| QQ | 建议用小号；协议端可等 Bot 启动后再配 |

---

## 1. 克隆仓库

在打算放牛的目录执行：

```bash
git clone https://github.com/PallasBot/Pallas-Bot.git
cd Pallas-Bot
```

**如何确认成功**：目录里有 `pyproject.toml`、`config/pallas.example.toml`。

---

## 2. 安装依赖

```bash
uv sync
```

::: details 打算用 PostgreSQL
```bash
uv sync --extra pg
```
:::

**如何确认成功**：

```bash
uv run python -c "import nonebot"
```

无报错即可。

---

## 3. 写主配置

```bash
cp config/pallas.example.toml config/pallas.toml
```

用编辑器打开 `config/pallas.toml`，**至少改这三项**：

```toml
[bootstrap]
host = "0.0.0.0"          # 监听所有网卡；仅本机玩可写 127.0.0.1
port = 8088
superusers = ["你的QQ号"]  # 超管，可填多个
db_backend = "mongodb"

[bootstrap.mongo]
host = "127.0.0.1"        # Docker 里连 compose 数据库时改为 mongodb
port = 27017
db = "PallasBot"
```

::: warning 别提交密钥
`pallas.toml` 已在 `.gitignore`，不要推到公开仓库。
:::

**如何确认成功**：`config/pallas.toml` 是普通**文件**（不是文件夹），且 `superusers` 已填。

---

## 4. 启动 Bot

```bash
uv run nb run
```

**如何确认成功**（对照日志）：

1. 没有数据库 `connection refused` 之类致命错误  
2. 日志里打印 **Web 控制台初始口令**（也可在 `data/pallas_console/` 找回）  
3. 浏览器打开 `http://127.0.0.1:8088/pallas/` 能出现登录页  

::: tip 控制台地址
- 本机：`http://127.0.0.1:8088/pallas/`  
- 远程：把 `127.0.0.1` 换成服务器 IP，并放行 **8088** 端口  
:::

---

## 5. 连接 QQ

Bot **不会**自己登录 QQ，需要 NapCat 等协议端转发消息。

1. 浏览器打开 `http://<主机>:8088/protocol/console/`  
2. 用与控制台相同方式登录  
3. **新建实例** → 选 NapCat → 手机 QQ 扫码  
4. 实例状态为 **在线**

群里发：

```text
牛牛帮助
```

应收到帮助图。逐步说明见 [连接 QQ / 协议端](connect-qq.md)。

**如何确认成功**：控制台 **协议端实例** 显示在线，且群内 **牛牛帮助** 有回复。

---

## 你已经跑起来了

▶ 想装决斗、MAA：[安装插件](install-plugins.md)  
▶ 想用网页改配置：[使用指南](../user/README.md)  
▶ 要上 VPS 长期跑：[标准部署](../Deployment.md)  

---

## 排障速查

| 现象 | 先看 |
| --- | --- |
| 数据库连不上 | Mongo/PG 是否已启动；`pallas.toml` 的 host/port/db 是否一致 |
| 忘记控制台口令 | [FAQ](../FAQ.md) |
| 协议端在线但群没反应 | 牛是否在群里；看 **运行日志** 是否收到消息 |
| 更多 | [FAQ](../FAQ.md) |
