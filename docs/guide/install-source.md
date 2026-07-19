# 源码安装

## 1. 下载 / 克隆仓库

```bash
git clone https://github.com/PallasBot/Pallas-Bot.git
cd Pallas-Bot
```

进目录后应能看到 `pyproject.toml`、`config/pallas.example.toml`。

## 2. 安装依赖

```bash
uv run pallas sync
```

::: details 可选：自检环境
```bash
uv run pallas doctor
```

还没有 `pallas.toml` 时，doctor 提示缺配置是正常的，下一步补上即可。
:::

## 3. 准备 PostgreSQL

需要一个**空库**（表会在首次启动时自动建）。下面 **二选一**。

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
:::

::: details 本机自己装 PostgreSQL
| 系统 | 文档 |
| --- | --- |
| Windows | [装 PostgreSQL（Windows）](/noobook/advance/windows/postgresql) |
| Linux / macOS | [PostgreSQL 官方下载](https://www.postgresql.org/download/) |

建空库（示例名 `PallasBot`），账号能建表即可。权限说明见 [deploy/pg](https://github.com/PallasBot/Pallas-Bot/blob/main/deploy/pg/README.md)。
:::

::: details 可选：库不存在时自动建库
在 `[bootstrap.postgres]` 加 `auto_create_db = true`（账号需有 `CREATEDB`）。上面 Docker 方式已经建好库时不必开。
:::

## 4. 写配置

复制一份配置：

::: code-group

```bash [Linux / macOS]
cp config/pallas.example.toml config/pallas.toml
```

```powershell [Windows]
copy config\pallas.example.toml config\pallas.toml
```

:::

编辑 `config/pallas.toml`，至少改这些（和上一步的库一致）：

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

## 5. 启动

```bash
uv run pallas
```

（等价于 `uv run pallas run unified`。）

- 日志里不应出现数据库 `connection refused`
- 会打印 **Web 控制台初始密码**（也可到 `data/pallas_console/` 找回）
- 浏览器打开：`http://127.0.0.1:8088/pallas/`

::: tip
本机用 `127.0.0.1`；挂到服务器请把访问地址换成公网 IP / 域名，并放行 **8088**。
:::

## 你已经跑通本体

▶ [连接 QQ](connect-qq.md)
