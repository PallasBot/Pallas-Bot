# 源码安装

完成本页后，Bot 会连接 PostgreSQL 并启动网页控制台。适合需要从源码运行、修改或参与开发的使用者。

## 1. 获得可运行的源码目录

```bash
git clone https://github.com/PallasBot/Pallas-Bot.git
cd Pallas-Bot
```

进入目录后，能看到 `pyproject.toml` 和 `config/pallas.example.toml`，说明位置正确。

## 2. 安装项目依赖

```bash
uv run pallas sync
```

命令完成且未报错后，依赖已就绪。

::: details 可选：自检环境
```bash
uv run pallas doctor
```

还没有 `pallas.toml` 时，doctor 提示缺配置是正常的，下一步补上即可。
:::

## 3. 准备可连接的 PostgreSQL 数据库

需要一个**空库**，首次启动时会自动建表。下面两种方式任选其一。

::: details 【推荐】Docker 起库
```bash
docker run -d --name pallas-pg \
  -e POSTGRES_USER=pallas \
  -e POSTGRES_PASSWORD=pallas \
  -e POSTGRES_DB=PallasBot \
  -p 5432:5432 \
  postgres:16-alpine

docker exec pallas-pg pg_isready
# 回复类似 accepting connections 即可
```
`pg_isready` 回复类似 `accepting connections`，说明数据库可以使用。
:::

::: details 本机自己装 PostgreSQL
| 系统 | 文档 |
| --- | --- |
| Windows | 装 PostgreSQL（Windows） |
| Linux / macOS | [PostgreSQL 官方下载](https://www.postgresql.org/download/) |

建一个空库（示例名 `PallasBot`），账号能建表即可。权限说明见 [deploy/pg](https://github.com/PallasBot/Pallas-Bot/blob/main/deploy/pg/README.md)。
:::

::: details 可选：库不存在时自动建库
在 `[bootstrap.postgres]` 加 `auto_create_db = true`（账号需有 `CREATEDB`）。上面 Docker 方式已经建好库时不必开。
:::

## 4. 生成并填写启动配置

复制一份配置：

::: code-group

```bash [Linux / macOS]
cp config/pallas.example.toml config/pallas.toml
```

```powershell [Windows]
copy config\pallas.example.toml config\pallas.toml
```

:::

编辑 `config/pallas.toml`，至少让以下配置与上一步创建的数据库一致：

```toml
[bootstrap]
host = "0.0.0.0"          # 仅本机可写 127.0.0.1
port = 8088
superusers = ["你的QQ号"]
db_backend = "postgresql"

[bootstrap.postgres]
host = "127.0.0.1"
port = 5432
user = "pallas"
password = "pallas"
db = "PallasBot"
```

::: warning
`pallas.toml` 已在 `.gitignore`，**不要**提交到公开仓库。
:::

配置保存后，Bot 已知道监听地址、超级用户和数据库位置。

## 5. 启动 Bot 并打开网页控制台

```bash
uv run pallas
```

这等价于 `uv run pallas run unified`。首次运行会创建数据库表，并在日志中打印 Web 控制台初始密码；这是正常现象。

- 日志中没有数据库 `connection refused`，且已打印**Web 控制台初始密码**，说明启动成功。密码也可在 `data/pallas_console/` 找回。
- 在浏览器打开 `http://127.0.0.1:8088/pallas/`，使用该密码登录。

::: tip
本机用 `127.0.0.1`；挂到服务器请把访问地址换成公网 IP / 域名，并放行 **8088**。
:::

## 接下来：登录控制台并连接 QQ

先阅读 [网页控制台](web-console.md) 登录并完成首次设置，再按 [连接 QQ](connect-qq.md) 扫码连接账号。
